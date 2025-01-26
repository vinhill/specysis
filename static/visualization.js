
async function loadAssociations() {
  const response = await fetch("/api/graph");
  const data = await response.json();

  // Convert { "ConceptA": ["Ref1","Ref2"], ... } into D3-friendly { nodes, links }
  const nodeSet = new Set();
  const links = [];

  for (const [source, targets] of Object.entries(data)) {
    nodeSet.add(source);
    for (const target of targets) {
      nodeSet.add(target);
      links.push({ source, target });
    }
  }

  console.log("Loaded graph:", { nodes: nodeSet.size, links: links.length });

  const nodes = Array.from(nodeSet).map(d => ({ id: d }));
  return { nodes, links };
}

function setRunning(simulation, running) {
  const freezeCheckbox = document.getElementById("freezeCheckbox");

  if (running) {
    simulation.restart();
    freezeCheckbox.checked = false;
  } else {
    simulation.stop();
    freezeCheckbox.checked = true;
  }
}

function shortestPath({ nodes, links }, startNode, endNode) {
  const adjacent = new Map(nodes.map(d => [d.id, []]));

  for (const { source, target } of links) {
    adjacent.get(source.id).push(target);
  }

  const visited = new Set();
  const queue = [[startNode]];

  while (queue.length) {
    const path = queue.shift();
    const node = path[path.length - 1];

    if (node === endNode) {
      return path;
    }

    if (visited.has(node)) {
      continue;
    }

    visited.add(node);

    for (const neighbor of adjacent.get(node.id)) {
      if (!visited.has(neighbor)) {
        queue.push([...path, neighbor]);
      }
    }
  }

  return null;
}

function createSimulation({ nodes, links }) {
  const container = document.getElementById("graph");
  const width = container.clientWidth;
  const height = container.clientHeight;

  // SVG
  const svg = d3.select(container)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .style("background-color", "#fafafa");

  const defs = svg.append("defs");

  for (let [id, color] of [["arrow-normal", "#999"], ["arrow-highlight", "#fcda1e"]]) {
  defs.append("marker")
    .attr("id", id)
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 15)
    .attr("refY", 0)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M0,-5L10,0L0,5") 
    .attr("fill", color);
  }

  // Group that we'll zoom/pan
  const g = svg.append("g");

  // Zoom & Pan
  const zoom = d3.zoom()
    .scaleExtent([0.1, 5])
    .on("zoom", (event) => {
      g.attr("transform", event.transform);
    });
  svg.call(zoom);

  // Force simulation
  const simulation = d3.forceSimulation(nodes)
    .force("charge", d3.forceManyBody().strength(-50))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("link", d3.forceLink(links).id(d => d.id).distance(80));

  // Links
  const link = g.selectAll(".link")
    .data(links)
    .enter()
    .append("line")
    .attr("class", "link")
    .attr("stroke", "#999")
    .attr("stroke-width", 1)
    .attr("stroke-opacity", 0.6)
    .attr("marker-end", "url(#arrow-normal)");

  // Nodes
  const node = g.selectAll(".node")
    .data(nodes)
    .enter()
    .append("circle")
    .attr("class", "node")
    .attr("r", 5)
    .attr("fill", "steelblue")
    .call(d3.drag()
      .on("drag", dragged)
      .on("end", dragEnded)
    )
    // On click, toggle highlight
    .on("click", (event, d) => toggleHighlight(d));

  // Labels
  const label = g.selectAll(".label")
    .data(nodes)
    .enter()
    .append("text")
    .attr("class", "label")
    .attr("font-size", 10)
    .attr("dx", 8)
    .attr("dy", 3)
    .text(d => d.id);

  // Each tick, redraw with updated positions
  simulation.on("tick", () => {
    link
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    node
      .attr("cx", d => d.x)
      .attr("cy", d => d.y);

    label
      .attr("x", d => d.x)
      .attr("y", d => d.y);
  });

  let dragging = false;
  function dragged(event, d) {
    if (!dragging) {
      dragging = true;
      simulation.alphaTarget(0.3);
      setRunning(simulation, true);
    }
    d.fx = d.x;
    d.fy = d.y;
    d.fx = event.x;
    d.fy = event.y;
  }

  function dragEnded(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    dragging = false;
    d.fx = null;
    d.fy = null;
  }

  // Track which node is selected
  let selectedNodes = new Set();

  // Toggle selection on click
  function toggleHighlight(d) {
    if (selectedNodes.has(d)) {
      selectedNodes.delete(d);
    } else {
      selectedNodes.add(d);
    }
    updateHighlights();
  }

  // Apply highlight classes
  function updateHighlights() {
    // Highlight each selected node
    node.classed("node-highlight", d => selectedNodes.has(d));

    // Highlight each link if it connects any selected node
    link.classed("link-highlight", l => {
      return selectedNodes.has(l.source) || selectedNodes.has(l.target);
    }).attr("marker-end", l => {
      return selectedNodes.has(l.source) ? "url(#arrow-highlight)" : "url(#arrow-normal)";
    });
  }

  function zoomToNode(d) {
    // Measure the rendered size
    const rect = svg.node().getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
  
    const transform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(1)
      .translate(-d.x, -d.y);
  
    // 3) Transition with the same 'zoom' object
    svg.transition()
      .duration(750)
      .call(zoom.transform, transform);
  }

  function search(query) {
    if (!query) return;

    const found = node.filter(d => d.id === query);
    if (!found.size()) {
      alert(`Node "${query}" not found!`);
      return;
    }
    const d = found.datum();

    selectedNodes.add(d);
    updateHighlights();

    zoomToNode(d);
  }

  function highlightPath(start, end) {
    const startNode = nodes.find(d => d.id === start);
    const endNode = nodes.find(d => d.id === end);

    if (!startNode || !endNode) {
      alert("Start or end node not found!");
      return;
    }

    const path = shortestPath({ nodes, links }, startNode, endNode);

    if (!path) {
      alert("No path found!");
      return;
    }

    selectedNodes = new Set(path);
    updateHighlights();

    path.forEach((d, i) => {
      setTimeout(() => {
        zoomToNode(d);
      }, i * 1000);
    });
  }

  return { simulation, controls: { search, highlightPath } };
}

/**
 * Returns `true` if all characters from `query` appear in `str` in the same order.
 * Fuzzy example: query="mr" => matches "Marianne" (M-a-r-...), or "Martha", or "Marigold".
 */
function fuzzyMatch(str, query) {
  str = str.toLowerCase();
  query = query.toLowerCase();

  let i = 0;
  let j = 0;
  while (i < str.length && j < query.length) {
    if (str[i] === query[j]) {
      j++;
    }
    i++;
  }
  return j === query.length;
}

function setupAutocompleteNames({ input, names }) {
  //<ul id="suggestions-i" class="suggestion-list" style="display: none;"></ul>
  const suggestions = document.createElement("ul");
  suggestions.classList.add("suggestion-list");
  suggestions.style.display = "none";
  
  input.insertAdjacentElement("afterend", suggestions);

  input.addEventListener("input", () => {
    const inputValue = input.value.trim();
    if (!inputValue || inputValue.length < 3) {
      suggestions.style.display = "none";
      return;
    }

    const filtered = names.filter((name) => fuzzyMatch(name, inputValue));

    // Clear old suggestions
    suggestions.innerHTML = "";

    if (filtered.length > 0) {
      filtered.forEach((name) => {
        const li = document.createElement("li");
        li.classList.add("suggestion-item");
        li.textContent = name;
        // When clicking on a suggestion, we fill the input
        li.addEventListener("click", () => {
          input.value = name;
          suggestions.style.display = "none";
        });
        suggestions.appendChild(li);
      });
      suggestions.style.display = "block";
    } else {
      suggestions.style.display = "none";
    }
  });

  input.addEventListener("blur", () => {
    suggestions.style.display = "none";
  });
}

function setupSearch({ search, names}) {
  const searchBtn = document.getElementById("searchBtn");
  const searchInput = document.getElementById("searchInput");

  searchBtn.addEventListener("click", () => search(searchInput.value));
  searchInput.addEventListener("keypress", (event) => {
    if (event.key === "Enter") search(searchInput.value);
  });

  setupAutocompleteNames({ input: searchInput, names });
}

function setupPathfinding({ highlightPath, names }) {
  const startInput = document.getElementById("startNodeInput");
  const endInput = document.getElementById("endNodeInput");
  const findPathBtn = document.getElementById("findPathBtn");

  setupAutocompleteNames({ input: startInput, names });
  setupAutocompleteNames({ input: endInput, names });

  findPathBtn.addEventListener("click", () => {
    const start = startInput.value;
    const end = endInput.value;

    if (!start || !end) {
      alert("Please provide both start and end nodes.");
      return;
    }

    highlightPath(start, end);
  });
}

function setupSimulationControls({ simulation, controls, names }) {
  const freezeCheckbox = document.getElementById("freezeCheckbox");
  const alphaDecayInput = document.getElementById("alphaDecayInput");
  const btnRestart = document.getElementById("btnRestart");

  freezeCheckbox.addEventListener("change", (event) => {
    setRunning(simulation, !event.target.checked);
  });
  if (freezeCheckbox.checked) {
    freezeCheckbox.checked = false;
  }

  alphaDecayInput.addEventListener("input", (event) => {
    const val = +event.target.value;
    simulation.alphaDecay(val);
  });
  simulation.alphaDecay(alphaDecayInput.value);

  btnRestart.addEventListener("click", () => {
    simulation.alpha(1);
    setRunning(simulation, true);
  });

  setupSearch({ search: controls.search, names });
  setupPathfinding({ highlightPath: controls.highlightPath, names });
}

// Main entry point
document.addEventListener("DOMContentLoaded", async () => {
  try {
    const graphData = await loadAssociations();
    const { simulation, controls } = createSimulation(graphData);
    const names = graphData.nodes.map(d => d.id);
    setupSimulationControls({ simulation, controls, names });
  } catch (err) {
    console.error("Error fetching or rendering graph data:", err);
  }
});
