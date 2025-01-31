import json
import logging
from dataclasses import dataclass
import re
import requests
from collections import Counter
from typing import List, Tuple

from tqdm import tqdm
from bs4 import BeautifulSoup, Comment, NavigableString
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def escape(el):
    el.insert_before(BeautifulSoup(f"<!-- {el} -->", "html.parser"))
    el.decompose()


def delete_section(soup, heading_id):
    heading = soup.find(id=heading_id)

    if not heading:
        logging.error("Heading with id %s not found.", heading_id)

    heading_level = heading.name
    # Find the next heading of the same level (e.g., <h2>, <h3>, etc.)
    next_heading = heading.find_next(lambda tag: tag.name == heading_level)

    # Remove everything till next_heading
    section = heading
    while section and section != next_heading:
        next_section = section.find_next_sibling()
        section.decompose()
        section = next_section

    return soup


def remove_uninteresting(soup):
    # Remove all comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove certain non-defining blocks
    blocks = [
        "example",
        "note",
        "warning",
        "XXX",
        "domintro",
        "idl",
        "html",
        "bookkeeping",
    ]
    for class_name in blocks:
        for element in soup.find_all(class_=class_name):
            element.decompose()

    delete_section(soup, "introduction")


def clean_token(token: str) -> str:
    # Remove quotes and extra whitespace, replace \n and \t with space
    return re.sub(r'\\?"|\s+', " ", token).strip()


@dataclass
class Config:
    # e.g. escape or lambda el: el.decompose()
    used_element_handler: callable = escape
    # html.parser or lxml
    parser: str = "lxml"


def extract_identifier(el) -> str:
    identifier = ""

    while el and not (identifier := el.get("id", "")):
        el = el.find_parent()

    return clean_token(identifier).strip()


def extract_refs(definition) -> set:
    refs = set()

    # find all anchors with href attribute
    for el in definition.find_all("a", href=True):
        if (href := el.get("href")) and href != "":
            ref = clean_token(href.split("#")[-1])
            refs.add(ref)

    return refs


def update_dict(d, cng):
    for k, v in cng.items():
        d[k] = v


class Definitions:
    def __init__(self):
        # { concept: { dependencies: [concepts], defined: bool, dfn_txt: str, name: str, ctype: str } }
        # possible types: callable, variable, value, unknown
        self._concepts = {}

    def n_concepts(self):
        return len(self._concepts)
    
    def n_defined_concepts(self):
        return sum(definition["defined"] for definition in self._concepts.values())
    
    def _ensure_concept(self, *concepts):
        for concept in concepts:
            if concept not in self._concepts:
                self._concepts[concept] = {
                    "dependencies": [], "defined": False, "dfn_txt": "", "name": "", "type": "unknown"
                }

    def set_ctype(self, identifier, ctype):
        self._ensure_concept(identifier)
        self._concepts[identifier]["ctype"] = ctype

    def get_ctype(self, identifier):
        if identifier in self._concepts:
            return self._concepts[identifier]["ctype"]
        logging.warning("get_ctype for unknown concept %s", identifier)

    def add_dfn(self, dfn, dependencies):
        name = clean_token(dfn.get_text(strip=True))
        identifier = extract_identifier(dfn)

        if not identifier:
            logging.warning("Cannot find identifier, skip adding dfn '%s'", str(dfn))
            return

        self._ensure_concept(identifier, *dependencies)

        if (concept := self._concepts[identifier]) and concept["defined"]:
            logging.warning("Redefinition of %s -- previous dfn_txt '%s' / new dfn_txt '%s'", identifier, concept["dfn_txt"], str(dfn))

        update_dict(self._concepts[identifier], {
            "dependencies": dependencies,
            "defined": True,
            "dfn_txt": str(dfn),
            "name": name,
        })

    def get_graph(self):
        # { concept: [dependencies] }
        return {
            concept: definition["dependencies"]
            for concept, definition in self._concepts.items()
        }


def text_between(el1, el2) -> str:
    """
    Given two BeautifulSoup elements el1 and el2, return the text between them.

    That is, the concatenation of all text nodes starting after the el1 tree,
    and stopping before the el2 tree.
    """
    chunks = []

    node = el1.next_sibling  # skip whole el1 tree
    while node and node != el2:
        if isinstance(node, NavigableString):
            chunks.append(node)
        node = node.next_element

    return "".join(chunks)


def is_multiple_dfn(dfns) -> bool:
    # Don't skip dfns of the form 'dfn, dfn and dfn'
    # we also ignore quotes and punctuation
    if len(dfns) <= 1:
        return False
    for i, el in enumerate(dfns):
        if i == 0:
            continue
        connecting_txt = text_between(dfns[i - 1], el)
        connecting_txt = clean_token(re.sub(r'[`\,\.]', '', connecting_txt))
        if connecting_txt not in ("and", "", "and"):
            logging.debug("Not multiple dfns due to connecting text '%s'", connecting_txt)
            return False
    return True


def is_dfn_and_concepts(dfns) -> bool:
    # Don't skip dfns if at most one has an id not starting with concept
    found_non_concept = False
    for dfn in dfns:
        if not extract_identifier(dfn).startswith("concept"):
            if found_non_concept:
                return False
            found_non_concept = True
    return True


def is_dfn_and_dfnfors(dfns) -> bool:
    # Don't skip dfn id if all but one have data-dfn-for=id
    dfn_fors = []
    dfns_nofor = []
    for dfn in dfns:
        if dfn.get("data-dfn-for"):
            dfn_fors.append(dfn)
        else:
            dfns_nofor.append(dfn)
    if len(dfns_nofor) != 1:
        return False
    dfn_id = extract_identifier(dfns_nofor[0])
    return all(dfn.get("data-dfn-for") == dfn_id for dfn in dfn_fors)


def extract_dfns(soup, definitions):
    cnt_skip_multiple = 0
    cnt_res_multiple = 0
    cnt_res_concepts = 0
    cnt_res_dfnfors = 0
    cnt_skip_unknown = 0
    cnt_skip_noid = 0

    for dfn in tqdm(soup.find_all("dfn")):
        parent = dfn.find_parent()

        if not parent:
            # TODO removing elements might cause us to miss dfns?
            # i.e. later in the used_element_handler
            logging.debug("No parent element, skipping extract dfn '%s'", dfn)
            continue

        if not extract_identifier(dfn):
            cnt_skip_noid += 1
            logging.debug("No identifier, skipping dfn '%s'", dfn)
            continue
        elif (dfns := parent.find_all("dfn")) and len(dfns) > 1:
            if is_multiple_dfn(dfns):
                cnt_res_multiple += 1
            elif is_dfn_and_concepts(dfns):
                cnt_res_concepts += 1
            elif is_dfn_and_dfnfors(dfns):
                cnt_res_dfnfors += 1
            else:
                # unclear which dfn belongs to the content
                cnt_skip_multiple += 1
                logging.debug("Skipping dfn due to multiple dfns in context -- '%s'", str(dfn))
                continue

        next_sibling = parent.find_next_sibling()

        # if concept defined by a list-represented algorithm
        if next_sibling and next_sibling.name in ("ol", "ul", "dl"):
            dependencies = list(extract_refs(next_sibling))
            definitions.add_dfn(dfn, dependencies)

            Config.used_element_handler(parent)
            Config.used_element_handler(next_sibling)

        # if concept defined as prose in the par
        elif not next_sibling or next_sibling.name in ("p",):
            dependencies = list(extract_refs(parent))
            definitions.add_dfn(dfn, dependencies)

            Config.used_element_handler(parent)

        else:
            cnt_skip_unknown += 1
            logging.debug("Cannot understand dfn '%s'", str(dfn))

    n_remaining_dfns = len(soup.find_all("dfn"))
    n_definitions = definitions.n_defined_concepts()
    extr_rate = n_definitions / (n_remaining_dfns + n_definitions)
    logging.info(
        "Extracted %d dnfs, remaining %d, quota %.2f",
        n_definitions, n_remaining_dfns, extr_rate
    )
    logging.info("Skipped %d dfns due to missing id", cnt_skip_noid)
    logging.info("Skipped %d dfns due to multiple dfns in context", cnt_skip_multiple)
    logging.info("Resolved %d multiple dfns by identifying conjunction", cnt_res_multiple)
    logging.info("Resolved %d multiple dfns by identifying at most one non-concept", cnt_res_concepts)
    logging.info("Resolved %d multiple dfns by identifying dfn and dfn-fors", cnt_res_dfnfors)
    logging.info("Skipped %d dfns due to not understanding them", cnt_skip_unknown)


def fetch_spec(download=True):
    if download:
        logging.info("Downloading spec")
        # We intentionally use the webpage and not the github source
        # as the webpage has ids for the dfns
        response = requests.get("https://html.spec.whatwg.org/")
        response.raise_for_status()
        spec = response.text

        with open("spec.html", "w", encoding="utf-8") as html_file:
            html_file.write(spec)
    else:
        logging.info("Skipping downloading spec")

        with open("spec.html", "r", encoding="utf-8") as html_file:
            spec = html_file.read()

    return spec


llm_client = OpenAI(
    base_url="http://127.0.0.1:8080/v1",
    api_key = "sk-no-key-required"
)

def llm_classify_dfn(parent, dfn):
    template = """
    ```
    {context}
    ```
    Classify the concept `#{identifier}` into one of these categories:
    "callable", "variable", "value", "unknown"
    Respond only with the category, nothing else.
    """

    context = str(parent)
    identifier = extract_identifier(dfn)
    if not identifier:
        logging.warning("Cannot find identifier, skip classifying dfn '%s'", str(dfn))
        return

    template = re.sub(r"\ +", " ", template)
    prompt = template.format(context=context, identifier=identifier)

    completion = llm_client.chat.completions.create(
        model="LLaMA_CPP",
        messages=[
            {"role": "system", "content": "You classify concepts from the WHATWG HTML Spec and complete tasks with highest precision."},
            {"role": "user", "content": prompt}
        ]
    )
    print(completion)
    res = completion.choices[0].message.content

    # TODO rather be a bit more forgiving and check if exactly one of the strings
    # is in the response?
    match = re.search(r'category="(.+?)".*', res)
    if not match:
        logging.warning("LLM categorization output incomprehensible: %s", res)
        return "unknown"

    ctype = match.group(1)

    if ctype not in ("callable", "variable", "value", "unknown"):
        logging.warning("LLM categorization output incomprehensible: %s", res)
        return "unknown"
    
    logging.info("LLM classified %s as %s", identifier, ctype)
    
    return ctype


def classify_dfns(soup, definitions):
    # TODO caching, have an override file for llm results
    for dfn in tqdm(soup.find_all("dfn")):
        parent = dfn.find_parent()    

        if not parent:
            logging.debug("No parent element, skipping classify dfn '%s'", dfn)
            continue

        res = llm_classify_dfn(parent, dfn)
        identifier = extract_identifier(dfn)
        definitions.set_ctype(identifier, res)

def main():
    source = fetch_spec(download=False)

    logging.info("Parsing source into soup")
    soup = BeautifulSoup(source, Config.parser)

    logging.info("Stripping of comments, notes etc.")
    remove_uninteresting(soup)

    logging.info("Classifying dfns")
    definitions = Definitions()
    classify_dfns(soup, definitions)

    logging.info("Extracting dfns")
    extract_dfns(soup, definitions)

    logging.info("Serializing remaining doc")
    unused_source = soup.decode()

    with open("static/graph.json", "w", encoding="utf-8") as json_file:
        json.dump(definitions.get_graph(), json_file, indent=4)

    with open("concepts.json", "w", encoding="utf-8") as json_file:
        json.dump(definitions._concepts, json_file, indent=4)

    with open("unused.html", "w", encoding="utf-8") as html_file:
        html_file.write(unused_source)


if __name__ == "__main__":
    main()
