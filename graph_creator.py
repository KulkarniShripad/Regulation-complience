#!/usr/bin/env python3
"""
Rule Graph Visualization Tool
Scans active rules and creates interactive graph visualizations
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import argparse

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np

# Optional imports for interactive visualization
try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("Plotly not available. Install with: pip install plotly")

try:
    from pyvis.network import Network
    PYVIS_AVAILABLE = True
except ImportError:
    PYVIS_AVAILABLE = False
    print("Pyvis not available. Install with: pip install pyvis")

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Color mapping for different domains and rule types
# ----------------------------------------------------------------------

DOMAIN_COLORS = {
    "MSME_LENDING": "#FF6B6B",  # Coral Red
    "KYC": "#4ECDC4",           # Turquoise
    "AML": "#45B7D1",           # Sky Blue
    "CAPITAL": "#96CEB4",       # Sage Green
    "NPA": "#FFEAA7",           # Light Orange
    "INTEREST_RATES": "#DDA0DD", # Plum
    "FOREIGN_EXCHANGE": "#98D8C8", # Mint
    "PRIORITY_SECTOR": "#F7D794", # Peach
    "GENERAL": "#C7CEE6",       # Lavender
    "DEFAULT": "#BDC3C7"        # Gray
}

RULE_TYPE_COLORS = {
    "PROHIBITION": "#FF6B6B",   # Red
    "MANDATE": "#4ECDC4",       # Green-Blue
    "PERMISSION": "#96CEB4",    # Green
    "LIMITATION": "#FFEAA7",    # Yellow
    "REPORTING": "#DDA0DD",     # Purple
    "EXEMPTION": "#F7D794",     # Orange
    "DEFAULT": "#BDC3C7"        # Gray
}

SEVERITY_COLORS = {
    "HIGH": "#FF6B6B",          # Red
    "MEDIUM": "#FFEAA7",        # Yellow
    "LOW": "#96CEB4"            # Green
}

# ----------------------------------------------------------------------
# Graph Building Functions
# ----------------------------------------------------------------------

def load_rules_from_folder(rules_dir: Path) -> Tuple[Dict[str, Dict], Dict[str, List[str]]]:
    """
    Load all active rules from the rules directory.
    Returns:
        - rules_dict: dict mapping rule_id to rule data
        - circular_map: dict mapping circular_id to list of rule_ids
    """
    rules_dict = {}
    circular_map = {}
    
    active_dir = rules_dir / "active"
    if not active_dir.exists():
        logger.error(f"Active rules directory not found: {active_dir}")
        return rules_dict, circular_map
    
    for rule_file in active_dir.glob("*.json"):
        try:
            with open(rule_file, "r", encoding="utf-8") as f:
                rule = json.load(f)
                rule_id = rule.get("rule_id")
                if rule_id and rule.get("status") == "ACTIVE":
                    rules_dict[rule_id] = rule
                    
                    # Map circular to rules
                    circular_id = rule.get("source", {}).get("circular_id", "UNKNOWN")
                    if circular_id not in circular_map:
                        circular_map[circular_id] = []
                    circular_map[circular_id].append(rule_id)
                    
        except Exception as e:
            logger.warning(f"Error loading rule {rule_file}: {e}")
    
    logger.info(f"Loaded {len(rules_dict)} active rules from {active_dir}")
    return rules_dict, circular_map


def build_rule_graph(rules_dict: Dict[str, Dict]) -> nx.DiGraph:
    """
    Build a directed graph from the rules with multiple edge types.
    """
    G = nx.DiGraph()
    
    # Add nodes with attributes
    for rule_id, rule in rules_dict.items():
        # Extract node attributes
        node_attrs = {
            "rule_id": rule_id,
            "rule_name": rule.get("rule_meta", {}).get("rule_name", "Unknown"),
            "domain": rule.get("rule_meta", {}).get("domain", "GENERAL"),
            "rule_type": rule.get("rule_meta", {}).get("rule_type", "MANDATE"),
            "severity": rule.get("rule_meta", {}).get("severity", "MEDIUM"),
            "circular_id": rule.get("source", {}).get("circular_id", "UNKNOWN"),
            "section": rule.get("source", {}).get("section", ""),
            "threshold_value": rule.get("logic", {}).get("threshold_value"),
            "threshold_field": rule.get("logic", {}).get("threshold_field", ""),
            "validator_type": rule.get("logic", {}).get("validator_type", "UNKNOWN")
        }
        G.add_node(rule_id, **node_attrs)
    
    # Add edges from graph_relations
    for rule_id, rule in rules_dict.items():
        relations = rule.get("graph_relations", {})
        
        # Add supersedes edges
        for sup in relations.get("supersedes", []):
            if sup in rules_dict:
                G.add_edge(rule_id, sup, relation="SUPERSEDES", color="#FF6B6B", weight=2)
        
        # Add requires_also_check edges
        for req in relations.get("requires_also_check", []):
            if req in rules_dict:
                G.add_edge(rule_id, req, relation="REQUIRES", color="#4ECDC4", weight=1)
        
        # Add exempted_by edges
        for exc in relations.get("exempted_by", []):
            if exc in rules_dict:
                G.add_edge(exc, rule_id, relation="EXEMPTS", color="#96CEB4", weight=1.5)
        
        # Add conflicts_with edges
        for conf in relations.get("conflicts_with", []):
            if conf in rules_dict:
                G.add_edge(rule_id, conf, relation="CONFLICTS", color="#FFEAA7", weight=1, style="dashed")
    
    # Add edges based on domain similarity (optional - for clustering)
    # This helps visualize domain groupings
    domains = {}
    for rule_id, attrs in G.nodes(data=True):
        domain = attrs.get("domain", "GENERAL")
        if domain not in domains:
            domains[domain] = []
        domains[domain].append(rule_id)
    
    # Add weak edges between same domain rules (dotted lines for visualization)
    for domain, rule_ids in domains.items():
        if len(rule_ids) > 1:
            for i in range(len(rule_ids) - 1):
                G.add_edge(rule_ids[i], rule_ids[i+1], 
                          relation="SAME_DOMAIN", 
                          color="#BDC3C7", 
                          weight=0.5,
                          style="dotted",
                          visible=False)  # Not shown by default
    
    logger.info(f"Built graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges")
    return G


def get_statistics(G: nx.DiGraph) -> Dict:
    """Calculate graph statistics."""
    stats = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "density": nx.density(G),
        "is_directed": G.is_directed(),
        "nodes_by_domain": {},
        "nodes_by_type": {},
        "nodes_by_severity": {},
        "most_connected": [],
        "isolated_nodes": list(nx.isolates(G))
    }
    
    # Count by domain
    for node, attrs in G.nodes(data=True):
        domain = attrs.get("domain", "GENERAL")
        stats["nodes_by_domain"][domain] = stats["nodes_by_domain"].get(domain, 0) + 1
        
        rule_type = attrs.get("rule_type", "MANDATE")
        stats["nodes_by_type"][rule_type] = stats["nodes_by_type"].get(rule_type, 0) + 1
        
        severity = attrs.get("severity", "MEDIUM")
        stats["nodes_by_severity"][severity] = stats["nodes_by_severity"].get(severity, 0) + 1
    
    # Find most connected nodes (degree centrality)
    if G.number_of_nodes() > 0:
        degrees = dict(G.degree())
        stats["most_connected"] = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return stats


# ----------------------------------------------------------------------
# Visualization Functions
# ----------------------------------------------------------------------

def visualize_matplotlib(G: nx.DiGraph, output_dir: Path, layout: str = "spring"):
    """
    Create static matplotlib visualization of the graph.
    """
    logger.info(f"Creating matplotlib visualization with {layout} layout...")
    
    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    
    # Choose layout
    if layout == "spring":
        pos = nx.spring_layout(G, k=2, iterations=50)
    elif layout == "kamada_kawai":
        pos = nx.kamada_kawai_layout(G)
    elif layout == "circular":
        pos = nx.circular_layout(G)
    elif layout == "shell":
        pos = nx.shell_layout(G)
    else:
        pos = nx.spring_layout(G)
    
    # Prepare node colors based on domain
    node_colors = []
    node_sizes = []
    for node in G.nodes():
        domain = G.nodes[node].get("domain", "GENERAL")
        node_colors.append(DOMAIN_COLORS.get(domain, DOMAIN_COLORS["DEFAULT"]))
        # Size based on degree (number of connections)
        degree = G.degree(node)
        node_sizes.append(800 + degree * 100)
    
    # Draw nodes
    nx.draw_networkx_nodes(G, pos, 
                          node_color=node_colors,
                          node_size=node_sizes,
                          alpha=0.8,
                          ax=ax)
    
    # Draw edges with different styles
    # Separate edges by type
    edges_by_type = {}
    for u, v, data in G.edges(data=True):
        edge_type = data.get("relation", "UNKNOWN")
        if edge_type not in edges_by_type:
            edges_by_type[edge_type] = []
        edges_by_type[edge_type].append((u, v))
    
    # Draw each edge type with different style
    edge_styles = {
        "SUPERSEDES": {"color": "#FF6B6B", "width": 2.5, "style": "solid", "alpha": 0.8},
        "REQUIRES": {"color": "#4ECDC4", "width": 2, "style": "solid", "alpha": 0.7},
        "EXEMPTS": {"color": "#96CEB4", "width": 2, "style": "solid", "alpha": 0.7},
        "CONFLICTS": {"color": "#FFEAA7", "width": 2, "style": "dashed", "alpha": 0.6},
        "SAME_DOMAIN": {"color": "#BDC3C7", "width": 0.5, "style": "dotted", "alpha": 0.3}
    }
    
    for edge_type, edges in edges_by_type.items():
        if edges:
            style = edge_styles.get(edge_type, edge_styles["REQUIRES"])
            nx.draw_networkx_edges(G, pos,
                                  edgelist=edges,
                                  edge_color=style["color"],
                                  width=style["width"],
                                  style=style["style"],
                                  alpha=style["alpha"],
                                  ax=ax,
                                  arrows=True,
                                  arrowsize=15)
    
    # Draw labels
    labels = {node: f"{node}\n{G.nodes[node].get('rule_name', '')[:30]}" 
              for node in G.nodes()}
    nx.draw_networkx_labels(G, pos, labels, font_size=8, ax=ax)
    
    # Get statistics for the legend
    # Count nodes by domain
    nodes_by_domain = {}
    for node in G.nodes():
        domain = G.nodes[node].get("domain", "GENERAL")
        nodes_by_domain[domain] = nodes_by_domain.get(domain, 0) + 1
    
    # Create legend for domains
    domain_patches = []
    for domain, color in DOMAIN_COLORS.items():
        if domain in nodes_by_domain:
            domain_patches.append(mpatches.Patch(
                color=color, 
                label=f"{domain} ({nodes_by_domain[domain]})"
            ))
    
    # Create legend for edge types
    edge_patches = []
    for edge_type, style in edge_styles.items():
        if edge_type in edges_by_type and edges_by_type[edge_type]:
            edge_patches.append(Line2D(
                [0], [0], 
                color=style["color"], 
                linewidth=style["width"], 
                linestyle=style["style"],
                label=edge_type
            ))
    
    # Add legends
    if domain_patches:
        legend1 = ax.legend(
            handles=domain_patches, 
            loc='upper left', 
            title="Rule Domains", 
            fontsize=8,
            bbox_to_anchor=(1.02, 1)
        )
        ax.add_artist(legend1)
    
    if edge_patches:
        legend2 = ax.legend(
            handles=edge_patches, 
            loc='lower left', 
            title="Edge Relations", 
            fontsize=8,
            bbox_to_anchor=(1.02, 0)
        )
        ax.add_artist(legend2)
    
    # Set title
    plt.title(f"RBI Circular Rules Graph\n"
              f"Total Rules: {G.number_of_nodes()} | "
              f"Relations: {G.number_of_edges()} | "
              f"Density: {nx.density(G):.3f}", 
              fontsize=14, fontweight='bold')
    
    plt.axis('off')
    plt.tight_layout()
    
    # Save figure
    output_file = output_dir / "rule_graph_matplotlib.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    logger.info(f"Saved matplotlib visualization to {output_file}")
    
    # Show plot
    plt.show()


def visualize_plotly(G: nx.DiGraph, output_dir: Path):
    """
    Create interactive Plotly visualization.
    """
    if not PLOTLY_AVAILABLE:
        logger.warning("Plotly not available. Skipping interactive visualization.")
        return
    
    logger.info("Creating Plotly interactive visualization...")
    
    # Get positions using spring layout
    pos = nx.spring_layout(G, k=2, iterations=50)
    
    # Prepare node traces
    node_x = []
    node_y = []
    node_text = []
    node_colors = []
    node_sizes = []
    
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        
        # Node text for hover
        attrs = G.nodes[node]
        text = (f"<b>Rule ID:</b> {node}<br>"
                f"<b>Name:</b> {attrs.get('rule_name', 'Unknown')}<br>"
                f"<b>Domain:</b> {attrs.get('domain', 'GENERAL')}<br>"
                f"<b>Type:</b> {attrs.get('rule_type', 'MANDATE')}<br>"
                f"<b>Severity:</b> {attrs.get('severity', 'MEDIUM')}<br>"
                f"<b>Circular:</b> {attrs.get('circular_id', 'Unknown')}<br>"
                f"<b>Threshold:</b> {attrs.get('threshold_field', 'N/A')} = {attrs.get('threshold_value', 'N/A')}")
        node_text.append(text)
        
        # Color based on severity
        severity = attrs.get('severity', 'MEDIUM')
        node_colors.append(SEVERITY_COLORS.get(severity, '#BDC3C7'))
        
        # Size based on degree centrality
        node_sizes.append(20 + G.degree(node) * 5)
    
    # Create node trace
    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode='markers+text',
        text=[f"{node}<br>{G.nodes[node].get('rule_name', '')[:20]}" for node in G.nodes()],
        textposition="top center",
        textfont=dict(size=8),
        hovertext=node_text,
        hoverinfo='text',
        marker=dict(
            size=node_sizes,
            color=node_colors,
            line=dict(color='white', width=1),
            opacity=0.8
        )
    )
    
    # Prepare edge traces
    edge_traces = []
    edge_types = {}
    
    for u, v, data in G.edges(data=True):
        edge_type = data.get('relation', 'UNKNOWN')
        if edge_type not in edge_types:
            edge_types[edge_type] = []
        edge_types[edge_type].append((u, v))
    
    # Color mapping for edge types
    edge_type_colors = {
        "SUPERSEDES": "#FF6B6B",
        "REQUIRES": "#4ECDC4",
        "EXEMPTS": "#96CEB4",
        "CONFLICTS": "#FFEAA7",
        "SAME_DOMAIN": "#BDC3C7"
    }
    
    for edge_type, edges in edge_types.items():
        edge_x = []
        edge_y = []
        for u, v in edges:
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])
        
        edge_trace = go.Scatter(
            x=edge_x,
            y=edge_y,
            mode='lines',
            line=dict(
                width=2,
                color=edge_type_colors.get(edge_type, "#BDC3C7"),
                dash='solid' if edge_type != "CONFLICTS" else 'dash'
            ),
            hoverinfo='none',
            name=edge_type
        )
        edge_traces.append(edge_trace)
    
    # Create figure
    fig = go.Figure(data=edge_traces + [node_trace],
                   layout=go.Layout(
                       title=dict(
                           text=f"RBI Circular Rules Graph - Interactive View<br>"
                                f"<sup>{G.number_of_nodes()} Rules, {G.number_of_edges()} Relations</sup>",
                           x=0.5,
                           font=dict(size=16)
                       ),
                       hovermode='closest',
                       showlegend=True,
                       legend=dict(
                           x=1.02,
                           y=1,
                           bgcolor='rgba(255, 255, 255, 0.8)',
                           bordercolor='black',
                           borderwidth=1
                       ),
                       xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                       yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                       width=1200,
                       height=800,
                       template='plotly_white'
                   ))
    
    # Save as HTML
    output_file = output_dir / "rule_graph_plotly.html"
    fig.write_html(str(output_file))
    logger.info(f"Saved Plotly interactive visualization to {output_file}")
    
    # Show in browser
    fig.show()


def visualize_pyvis(G: nx.DiGraph, output_dir: Path):
    """
    Create interactive network visualization with Pyvis.
    """
    if not PYVIS_AVAILABLE:
        logger.warning("Pyvis not available. Skipping network visualization.")
        return
    
    logger.info("Creating Pyvis interactive network visualization...")
    
    # Create network
    net = Network(height="800px", width="100%", directed=True, bgcolor="#ffffff", font_color="black")
    
    # Set options
    net.set_options("""
    var options = {
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -2000,
          "centralGravity": 0.3,
          "springLength": 95,
          "springConstant": 0.04,
          "damping": 0.09,
          "avoidOverlap": 0.1
        }
      },
      "edges": {
        "smooth": true,
        "arrows": {
          "to": {"enabled": true, "scaleFactor": 0.5}
        }
      }
    }
    """)
    
    # Add nodes
    for node, attrs in G.nodes(data=True):
        # Color based on domain
        domain = attrs.get('domain', 'GENERAL')
        color = DOMAIN_COLORS.get(domain, DOMAIN_COLORS["DEFAULT"])
        
        # Size based on degree
        size = 20 + G.degree(node) * 3
        
        # Title for hover
        title = (f"<b>{node}</b><br>"
                f"Name: {attrs.get('rule_name', 'Unknown')}<br>"
                f"Domain: {domain}<br>"
                f"Type: {attrs.get('rule_type', 'MANDATE')}<br>"
                f"Severity: {attrs.get('severity', 'MEDIUM')}<br>"
                f"Circular: {attrs.get('circular_id', 'Unknown')}")
        
        net.add_node(node, 
                    label=f"{node}\n{attrs.get('rule_name', '')[:20]}",
                    title=title,
                    color=color,
                    size=size)
    
    # Add edges
    for u, v, data in G.edges(data=True):
        edge_type = data.get('relation', 'UNKNOWN')
        # Color based on edge type
        if edge_type == "SUPERSEDES":
            color = "#FF6B6B"
            width = 3
        elif edge_type == "REQUIRES":
            color = "#4ECDC4"
            width = 2
        elif edge_type == "EXEMPTS":
            color = "#96CEB4"
            width = 2
        elif edge_type == "CONFLICTS":
            color = "#FFEAA7"
            width = 2
        else:
            color = "#BDC3C7"
            width = 1
        
        net.add_edge(u, v, 
                    title=edge_type,
                    color=color,
                    width=width,
                    arrows='to' if G.is_directed() else None)
    
    # Save as HTML
    output_file = output_dir / "rule_graph_pyvis.html"
    net.save_graph(str(output_file))
    logger.info(f"Saved Pyvis interactive visualization to {output_file}")


def print_statistics(stats: Dict):
    """Print graph statistics in a formatted way."""
    print("\n" + "="*60)
    print("RULE GRAPH STATISTICS")
    print("="*60)
    
    print(f"\n📊 Overall Statistics:")
    print(f"   • Total Rules: {stats['total_nodes']}")
    print(f"   • Total Relations: {stats['total_edges']}")
    print(f"   • Graph Density: {stats['density']:.4f}")
    print(f"   • Is Directed: {stats['is_directed']}")
    
    print(f"\n📁 Rules by Domain:")
    for domain, count in sorted(stats['nodes_by_domain'].items(), key=lambda x: x[1], reverse=True):
        print(f"   • {domain}: {count} rules")
    
    print(f"\n🏷️ Rules by Type:")
    for rule_type, count in sorted(stats['nodes_by_type'].items(), key=lambda x: x[1], reverse=True):
        print(f"   • {rule_type}: {count} rules")
    
    print(f"\n⚠️ Rules by Severity:")
    for severity, count in sorted(stats['nodes_by_severity'].items(), key=lambda x: x[1], reverse=True):
        print(f"   • {severity}: {count} rules")
    
    print(f"\n🔗 Most Connected Rules (Top 5):")
    for rule_id, degree in stats['most_connected'][:5]:
        print(f"   • {rule_id}: {degree} connections")
    
    if stats['isolated_nodes']:
        print(f"\n🔘 Isolated Rules (no relations): {len(stats['isolated_nodes'])}")
        for node in stats['isolated_nodes'][:5]:
            print(f"   • {node}")
        if len(stats['isolated_nodes']) > 5:
            print(f"   • ... and {len(stats['isolated_nodes']) - 5} more")
    
    print("="*60 + "\n")


def export_graph_data(G: nx.DiGraph, output_dir: Path):
    """
    Export graph data in various formats for further analysis.
    Handles None values by converting them to empty strings or appropriate defaults.
    """
    # Export as JSON
    graph_data = {
        "nodes": [],
        "edges": []
    }
    
    for node, attrs in G.nodes(data=True):
        # Convert None values to null (JSON handles this naturally)
        node_data = {"id": node}
        for key, value in attrs.items():
            node_data[key] = value
        graph_data["nodes"].append(node_data)
    
    for u, v, attrs in G.edges(data=True):
        edge_data = {
            "source": u,
            "target": v
        }
        for key, value in attrs.items():
            edge_data[key] = value
        graph_data["edges"].append(edge_data)
    
    json_file = output_dir / "graph_data.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Exported graph data to {json_file}")
    
    # Export as GraphML (with None handling)
    # Create a copy of the graph with None values replaced
    G_for_graphml = nx.DiGraph()
    
    # Add nodes with None values replaced
    for node, attrs in G.nodes(data=True):
        cleaned_attrs = {}
        for key, value in attrs.items():
            if value is None:
                cleaned_attrs[key] = ""  # Replace None with empty string
            else:
                cleaned_attrs[key] = value
        G_for_graphml.add_node(node, **cleaned_attrs)
    
    # Add edges with None values replaced
    for u, v, attrs in G.edges(data=True):
        cleaned_attrs = {}
        for key, value in attrs.items():
            if value is None:
                cleaned_attrs[key] = ""  # Replace None with empty string
            else:
                cleaned_attrs[key] = value
        G_for_graphml.add_edge(u, v, **cleaned_attrs)
    
    try:
        graphml_file = output_dir / "rule_graph.graphml"
        nx.write_graphml(G_for_graphml, graphml_file)
        logger.info(f"Exported GraphML to {graphml_file}")
    except Exception as e:
        logger.warning(f"Could not export GraphML: {e}")
        logger.info("Skipping GraphML export due to compatibility issues")
    
    # Export as GEXF (with None handling)
    try:
        gexf_file = output_dir / "rule_graph.gexf"
        nx.write_gexf(G_for_graphml, gexf_file)
        logger.info(f"Exported GEXF to {gexf_file}")
    except Exception as e:
        logger.warning(f"Could not export GEXF: {e}")
        logger.info("Skipping GEXF export due to compatibility issues")
    
    # Export as simple edge list (useful for other tools)
    edge_list_file = output_dir / "edge_list.txt"
    with open(edge_list_file, "w") as f:
        for u, v, data in G.edges(data=True):
            relation = data.get('relation', 'unknown')
            f.write(f"{u}\t{v}\t{relation}\n")
    logger.info(f"Exported edge list to {edge_list_file}")
    
    # Export as node list
    node_list_file = output_dir / "node_list.txt"
    with open(node_list_file, "w") as f:
        for node, attrs in G.nodes(data=True):
            domain = attrs.get('domain', 'GENERAL')
            rule_type = attrs.get('rule_type', 'MANDATE')
            severity = attrs.get('severity', 'MEDIUM')
            f.write(f"{node}\t{domain}\t{rule_type}\t{severity}\t{attrs.get('rule_name', 'Unknown')}\n")
    logger.info(f"Exported node list to {node_list_file}")

# ----------------------------------------------------------------------
# Main Function
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Visualize rule graph from RBI circulars")
    parser.add_argument("--rules-dir", default="./my_rules", 
                       help="Directory containing rules (default: ./my_rules)")
    parser.add_argument("--output-dir", default="./graph_output",
                       help="Output directory for visualizations (default: ./graph_output)")
    parser.add_argument("--layout", choices=["spring", "kamada_kawai", "circular", "shell"],
                       default="spring", help="Graph layout for matplotlib (default: spring)")
    parser.add_argument("--format", choices=["matplotlib", "plotly", "pyvis", "all"],
                       default="all", help="Visualization format (default: all)")
    parser.add_argument("--no-stats", action="store_true",
                       help="Don't print statistics")
    parser.add_argument("--no-export", action="store_true",
                       help="Don't export graph data")
    
    args = parser.parse_args()
    
    # Setup directories
    rules_dir = Path(args.rules_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load rules
    logger.info(f"Loading rules from {rules_dir}")
    rules_dict, circular_map = load_rules_from_folder(rules_dir)
    
    if not rules_dict:
        logger.error("No active rules found. Exiting.")
        return
    
    # Build graph
    logger.info("Building rule graph...")
    G = build_rule_graph(rules_dict)
    
    # Print statistics
    if not args.no_stats:
        stats = get_statistics(G)
        print_statistics(stats)
    
    # Create visualizations
    if args.format in ["matplotlib", "all"]:
        visualize_matplotlib(G, output_dir, args.layout)
    
    if args.format in ["plotly", "all"]:
        visualize_plotly(G, output_dir)
    
    if args.format in ["pyvis", "all"]:
        visualize_pyvis(G, output_dir)
    
    # Export data
    if not args.no_export:
        export_graph_data(G, output_dir)
    
    logger.info(f"\n✅ All visualizations saved to: {output_dir}")
    logger.info("   Open HTML files in browser for interactive views.")


if __name__ == "__main__":
    main()
