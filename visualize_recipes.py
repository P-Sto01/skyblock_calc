from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import networkx as nx

GRID_SLOTS = ("A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3")


def load_recipes(path: Path) -> dict[str, dict]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_ingredient(raw_value: str) -> tuple[str, int]:
    raw_value = str(raw_value).strip()
    if not raw_value:
        return "", 0

    if ":" not in raw_value:
        return raw_value, 1

    item_name, maybe_count = raw_value.rsplit(":", 1)
    try:
        return item_name, int(maybe_count)
    except ValueError:
        return raw_value, 1


def build_recipe_graph(recipes: dict[str, dict]) -> nx.DiGraph:
    graph = nx.DiGraph()

    for output_item, recipe in recipes.items():
        recipe = recipe or {}
        graph.add_node(
            output_item,
            craftable=bool(recipe),
            recipe_count=recipe.get("count", 1),
            duration=recipe.get("duration", 0),
            coins=recipe.get("coins", 0),
        )

        for slot in GRID_SLOTS:
            ingredient_name, quantity = parse_ingredient(recipe.get(slot, ""))
            if not ingredient_name:
                continue

            if ingredient_name not in graph:
                graph.add_node(ingredient_name, craftable=bool(recipes.get(ingredient_name)))

            if graph.has_edge(ingredient_name, output_item):
                graph[ingredient_name][output_item]["quantity"] += quantity
                graph[ingredient_name][output_item]["slots"].append(slot)
            else:
                graph.add_edge(
                    ingredient_name,
                    output_item,
                    quantity=quantity,
                    slots=[slot],
                )

    return graph


def trim_graph(graph: nx.DiGraph, max_nodes: int) -> nx.DiGraph:
    if graph.number_of_nodes() <= max_nodes:
        return graph.copy()

    ranked_nodes = sorted(graph.degree, key=lambda pair: pair[1], reverse=True)
    keep = [node for node, _ in ranked_nodes[:max_nodes]]
    return graph.subgraph(keep).copy()


def neighborhood_subgraph(graph: nx.DiGraph, center_item: str, depth: int) -> nx.DiGraph:
    if center_item not in graph:
        known = ", ".join(sorted(list(graph.nodes))[:10])
        raise KeyError(f"'{center_item}' was not found in the graph. Example items: {known}...")

    distances = nx.single_source_shortest_path_length(graph.to_undirected(), center_item, cutoff=depth)
    return graph.subgraph(distances.keys()).copy()


def default_subgraph(graph: nx.DiGraph, max_nodes: int) -> nx.DiGraph:
    if graph.number_of_nodes() <= max_nodes:
        return graph.copy()

    largest_component = max(nx.weakly_connected_components(graph), key=len)
    component_graph = graph.subgraph(largest_component).copy()
    return trim_graph(component_graph, max_nodes)


def draw_graph(graph: nx.DiGraph, title: str, save_path: Path | None = None) -> None:
    plt.figure(figsize=(16, 10))
    pos = nx.spring_layout(graph, seed=42, k=1.2, iterations=200)

    craftable_nodes = [node for node, data in graph.nodes(data=True) if data.get("craftable")]
    material_nodes = [node for node in graph.nodes if node not in craftable_nodes]

    nx.draw_networkx_nodes(
        graph,
        pos,
        nodelist=craftable_nodes,
        node_color="#60a5fa",
        node_size=900,
        edgecolors="#1e3a8a",
        linewidths=1.0,
    )
    nx.draw_networkx_nodes(
        graph,
        pos,
        nodelist=material_nodes,
        node_color="#f59e0b",
        node_size=800,
        edgecolors="#92400e",
        linewidths=1.0,
    )

    edge_widths = [1 + min(data.get("quantity", 1) / 8, 4) for _, _, data in graph.edges(data=True)]
    nx.draw_networkx_edges(
        graph,
        pos,
        width=edge_widths,
        edge_color="#94a3b8",
        arrows=True,
        arrowsize=16,
        connectionstyle="arc3,rad=0.08",
    )

    if graph.number_of_nodes() > 80:
        label_nodes = {
            node
            for node, _ in sorted(graph.degree, key=lambda pair: pair[1], reverse=True)[:80]
        }
        labels = {node: node for node in graph.nodes if node in label_nodes}
    else:
        labels = {node: node for node in graph.nodes}

    nx.draw_networkx_labels(graph, pos, labels=labels, font_size=8, font_weight="bold")

    if graph.number_of_edges() <= 60:
        edge_labels = {
            (source, target): data.get("quantity", 1)
            for source, target, data in graph.edges(data=True)
        }
        nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=7)

    plt.title(title)
    plt.axis("off")
    plt.tight_layout()

    if save_path is not None:
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        print(f"Saved graph image to: {save_path}")
    else:
        plt.show()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load Skyblock recipes into NetworkX and visualize them.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).with_name("recipes.json"),
        help="Path to the recipes JSON file.",
    )
    parser.add_argument(
        "--item",
        type=str,
        help="Optional item id to center the visualization around, e.g. ENCHANTED_BREAD.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=2,
        help="Neighborhood depth around --item.",
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=120,
        help="Maximum nodes to draw so the plot stays readable.",
    )
    parser.add_argument(
        "--save",
        type=Path,
        help="Optional output image path, e.g. recipe_graph.png.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    recipes = load_recipes(args.input)
    graph = build_recipe_graph(recipes)

    print(f"Loaded {len(recipes):,} recipes")
    print(f"Graph has {graph.number_of_nodes():,} nodes and {graph.number_of_edges():,} edges")

    if args.item:
        selected_graph = neighborhood_subgraph(graph, args.item, args.depth)
        selected_graph = trim_graph(selected_graph, args.max_nodes)
        title = f"Recipe neighborhood for {args.item}"
    else:
        selected_graph = default_subgraph(graph, args.max_nodes)
        title = "Skyblock recipe graph (largest component sample)"

    print(
        f"Visualizing {selected_graph.number_of_nodes():,} nodes and "
        f"{selected_graph.number_of_edges():,} edges"
    )
    draw_graph(selected_graph, title=title, save_path=args.save)


if __name__ == "__main__":
    main()
