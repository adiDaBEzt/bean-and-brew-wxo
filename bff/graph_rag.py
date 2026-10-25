"""Bean & Brew Graph RAG (Knowledge Graph Engine).

Provides multi-hop relationship retrieval across the Bean & Brew supply chain,
recipes, stores, suppliers, and allergen data.

Graph Model:
- Nodes: (id, label, type, properties)
- Edges: (source_id, target_id, relation_type, properties)

Enables queries like:
- "What drinks use ingredients supplied by Oatly?"
- "Which allergens exist in drinks sold at Store S01?"
- "If SKU-OAT-001 has a shipment delay, which stores and recipes are impacted?"
"""
import json
import pathlib
import sqlite3
from typing import Any, Dict, List, Optional, Set

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
GRAPH_DB_PATH = DATA_DIR / "knowledge_graph.db"


def init_graph_db(db_path: pathlib.Path = GRAPH_DB_PATH) -> None:
    """Initialize SQLite tables for Knowledge Graph nodes and edges."""
    db_path = pathlib.Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                node_type TEXT NOT NULL,
                properties TEXT DEFAULT '{}'
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                properties TEXT DEFAULT '{}',
                PRIMARY KEY (source_id, target_id, relation),
                FOREIGN KEY (source_id) REFERENCES graph_nodes(id),
                FOREIGN KEY (target_id) REFERENCES graph_nodes(id)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edge_source ON graph_edges(source_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edge_target ON graph_edges(target_id);")
        conn.commit()


def seed_bean_brew_knowledge_graph(db_path: pathlib.Path = GRAPH_DB_PATH) -> None:
    """Seed comprehensive specialty coffee supply chain, recipes, and store network."""
    init_graph_db(db_path)
    
    nodes = [
        # Stores
        ("STORE-S01", "Downtown Flagship (S01)", "Store", {"region": "NORTH", "city": "Seattle", "manager": "Sam Rivera"}),
        ("STORE-S02", "Uptown Roastery (S02)", "Store", {"region": "NORTH", "city": "Seattle", "manager": "Carlos Mendez"}),
        ("STORE-S03", "Metro Station (S03)", "Store", {"region": "NORTH", "city": "Bellevue", "manager": "Elena Rostova"}),
        ("STORE-S04", "South Lake Union (S04)", "Store", {"region": "SOUTH", "city": "Portland", "manager": "David Kim"}),
        
        # Regions
        ("REGION-NORTH", "North Region", "Region", {"director": "Priya Nair", "stores_count": 3}),
        ("REGION-SOUTH", "South Region", "Region", {"director": "Marcus Vance", "stores_count": 1}),
        
        # Menu Drinks
        ("DRINK-OAT-LATTE", "Artisan Oat Milk Latte", "MenuItem", {"category": "Espresso", "price": 5.75, "roast": "Light"}),
        ("DRINK-VANILLA-COLDBREW", "Vanilla Cream Cold Brew", "MenuItem", {"category": "Cold Brew", "price": 6.25, "roast": "Dark"}),
        ("DRINK-CARAMEL-CAPPUCCINO", "Salted Caramel Cappuccino", "MenuItem", {"category": "Espresso", "price": 5.50, "roast": "Medium"}),
        ("DRINK-MATCHA-LATTE", "Ceremonial Oat Matcha", "MenuItem", {"category": "Tea", "price": 6.00, "roast": "None"}),
        
        # Raw Ingredients / SKUs
        ("SKU-OAT-001", "Barista Edition Oat Milk", "Ingredient", {"unit": "liter", "shelf_life_days": 180, "reorder_point": 50}),
        ("SKU-ESP-001", "Signature Espresso Beans", "Ingredient", {"unit": "kg", "origin": "Ethiopia & Colombia", "reorder_point": 30}),
        ("SKU-VAN-001", "Madagascar Vanilla Syrup", "Ingredient", {"unit": "bottle", "organic": True, "reorder_point": 20}),
        ("SKU-CAR-001", "Organic Salted Caramel Sauce", "Ingredient", {"unit": "bottle", "organic": True, "reorder_point": 15}),
        ("SKU-MAT-001", "Ceremonial Grade Matcha Powder", "Ingredient", {"unit": "kg", "origin": "Uji, Japan", "reorder_point": 10}),
        
        # Suppliers
        ("SUP-OATLY", "Oatly Commercial Supply", "Supplier", {"lead_time_days": 3, "reliability": 0.98, "contact": "supply@oatly.example"}),
        ("SUP-LOCAL-ROAST", "Pacific Roastery Guild", "Supplier", {"lead_time_days": 2, "reliability": 0.99, "contact": "orders@pacificguild.example"}),
        ("SUP-ORGANIC-SYRUPS", "Monin Artisan Craft", "Supplier", {"lead_time_days": 5, "reliability": 0.95, "contact": "b2b@monin-artisan.example"}),
        ("SUP-KYOTO-TEA", "Kyoto Uji Tea Importers", "Supplier", {"lead_time_days": 7, "reliability": 0.96, "contact": "kyoto-export@uji.example"}),
        
        # Allergens
        ("ALLERGEN-DAIRY", "Dairy / Lactose", "Allergen", {"severity": "High"}),
        ("ALLERGEN-GLUTEN", "Gluten (Trace Oat)", "Allergen", {"severity": "Low"}),
        ("ALLERGEN-SOY", "Soy Protein", "Allergen", {"severity": "Moderate"}),
        
        # Equipment
        ("EQ-LA-MARZOCCO", "La Marzocco Linea PB 3-Group", "Equipment", {"service_interval_days": 90, "pressure_bars": 9}),
        ("EQ-MAHLKONIG", "Mahlkönig EK43S Grinder", "Equipment", {"burr_size_mm": 98, "calibration_frequency": "daily"}),
    ]

    edges = [
        # Store -> Region
        ("STORE-S01", "REGION-NORTH", "LOCATED_IN", {}),
        ("STORE-S02", "REGION-NORTH", "LOCATED_IN", {}),
        ("STORE-S03", "REGION-NORTH", "LOCATED_IN", {}),
        ("STORE-S04", "REGION-SOUTH", "LOCATED_IN", {}),
        
        # Drink -> Ingredient
        ("DRINK-OAT-LATTE", "SKU-OAT-001", "USES_INGREDIENT", {"quantity_per_serving": "250ml"}),
        ("DRINK-OAT-LATTE", "SKU-ESP-001", "USES_INGREDIENT", {"quantity_per_serving": "18g"}),
        ("DRINK-VANILLA-COLDBREW", "SKU-VAN-001", "USES_INGREDIENT", {"quantity_per_serving": "30ml"}),
        ("DRINK-VANILLA-COLDBREW", "SKU-ESP-001", "USES_INGREDIENT", {"quantity_per_serving": "35g"}),
        ("DRINK-CARAMEL-CAPPUCCINO", "SKU-CAR-001", "USES_INGREDIENT", {"quantity_per_serving": "25ml"}),
        ("DRINK-CARAMEL-CAPPUCCINO", "SKU-ESP-001", "USES_INGREDIENT", {"quantity_per_serving": "18g"}),
        ("DRINK-MATCHA-LATTE", "SKU-MAT-001", "USES_INGREDIENT", {"quantity_per_serving": "5g"}),
        ("DRINK-MATCHA-LATTE", "SKU-OAT-001", "USES_INGREDIENT", {"quantity_per_serving": "250ml"}),
        
        # Supplier -> Ingredient
        ("SUP-OATLY", "SKU-OAT-001", "SUPPLIES", {"contract_tier": "Enterprise Gold"}),
        ("SUP-LOCAL-ROAST", "SKU-ESP-001", "SUPPLIES", {"contract_tier": "Local Roaster Tier 1"}),
        ("SUP-ORGANIC-SYRUPS", "SKU-VAN-001", "SUPPLIES", {"contract_tier": "Direct Importer"}),
        ("SUP-ORGANIC-SYRUPS", "SKU-CAR-001", "SUPPLIES", {"contract_tier": "Direct Importer"}),
        ("SUP-KYOTO-TEA", "SKU-MAT-001", "SUPPLIES", {"contract_tier": "Direct Air Freight"}),
        
        # Ingredient -> Allergen
        ("SKU-OAT-001", "ALLERGEN-GLUTEN", "CONTAINS_ALLERGEN", {"note": "Certified gluten-free certified facility, trace cross-contact only"}),
        ("SKU-CAR-001", "ALLERGEN-DAIRY", "CONTAINS_ALLERGEN", {"note": "Contains real butter and heavy cream"}),
        
        # Store -> Menu Availability
        ("STORE-S01", "DRINK-OAT-LATTE", "OFFERS_MENU_ITEM", {"popularity_rank": 1}),
        ("STORE-S01", "DRINK-VANILLA-COLDBREW", "OFFERS_MENU_ITEM", {"popularity_rank": 2}),
        ("STORE-S01", "DRINK-CARAMEL-CAPPUCCINO", "OFFERS_MENU_ITEM", {"popularity_rank": 3}),
        ("STORE-S01", "DRINK-MATCHA-LATTE", "OFFERS_MENU_ITEM", {"popularity_rank": 4}),
        ("STORE-S02", "DRINK-OAT-LATTE", "OFFERS_MENU_ITEM", {"popularity_rank": 1}),
        ("STORE-S02", "DRINK-VANILLA-COLDBREW", "OFFERS_MENU_ITEM", {"popularity_rank": 2}),
        ("STORE-S03", "DRINK-OAT-LATTE", "OFFERS_MENU_ITEM", {"popularity_rank": 1}),
        ("STORE-S04", "DRINK-CARAMEL-CAPPUCCINO", "OFFERS_MENU_ITEM", {"popularity_rank": 1}),
        
        # Store -> Equipment
        ("STORE-S01", "EQ-LA-MARZOCCO", "OPERATES", {"install_date": "2024-01-15"}),
        ("STORE-S01", "EQ-MAHLKONIG", "OPERATES", {"install_date": "2024-01-15"}),
        ("STORE-S02", "EQ-LA-MARZOCCO", "OPERATES", {"install_date": "2024-03-20"}),
    ]

    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        for nid, name, ntype, props in nodes:
            conn.execute(
                """
                INSERT INTO graph_nodes (id, name, node_type, properties)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, node_type=excluded.node_type, properties=excluded.properties
                """,
                (nid, name, ntype, json.dumps(props)),
            )
        for src, tgt, rel, props in edges:
            conn.execute(
                """
                INSERT INTO graph_edges (source_id, target_id, relation, properties)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation) DO UPDATE SET properties=excluded.properties
                """,
                (src, tgt, rel, json.dumps(props)),
            )
        conn.commit()


def query_subgraph(entity_query: str, depth: int = 2, db_path: pathlib.Path = GRAPH_DB_PATH) -> Dict[str, Any]:
    """Perform multi-hop traversal around nodes matching `entity_query`."""
    db_path = pathlib.Path(db_path)
    if not db_path.exists():
        seed_bean_brew_knowledge_graph(db_path)

    query_term = (entity_query or "").strip().lower()

    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Match seed nodes by name or ID
        cur.execute(
            """
            SELECT id, name, node_type, properties
            FROM graph_nodes
            WHERE lower(id) LIKE ? OR lower(name) LIKE ? OR lower(node_type) LIKE ?
            LIMIT 10
            """,
            (f"%{query_term}%", f"%{query_term}%", f"%{query_term}%"),
        )
        seed_rows = cur.fetchall()
        if not seed_rows:
            # Fallback to returning all nodes if empty query
            cur.execute("SELECT id, name, node_type, properties FROM graph_nodes LIMIT 8")
            seed_rows = cur.fetchall()

        matched_nodes: Dict[str, Dict[str, Any]] = {}
        for r in seed_rows:
            matched_nodes[r["id"]] = {
                "id": r["id"],
                "name": r["name"],
                "type": r["node_type"],
                "properties": json.loads(r["properties"] or "{}"),
            }

        visited_edges: List[Dict[str, Any]] = []
        frontier = set(matched_nodes.keys())
        seen_nodes = set(frontier)

        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            params = list(frontier) * 2

            cur.execute(
                f"""
                SELECT e.source_id, e.target_id, e.relation, e.properties,
                       s.name as source_name, s.node_type as source_type,
                       t.name as target_name, t.node_type as target_type,
                       s.properties as source_props, t.properties as target_props
                FROM graph_edges e
                JOIN graph_nodes s ON e.source_id = s.id
                JOIN graph_nodes t ON e.target_id = t.id
                WHERE e.source_id IN ({placeholders}) OR e.target_id IN ({placeholders})
                """,
                params,
            )
            rows = cur.fetchall()
            next_frontier: Set[str] = set()

            for r in rows:
                edge_dict = {
                    "source": r["source_id"],
                    "source_name": r["source_name"],
                    "source_type": r["source_type"],
                    "relation": r["relation"],
                    "target": r["target_id"],
                    "target_name": r["target_name"],
                    "target_type": r["target_type"],
                    "properties": json.loads(r["properties"] or "{}"),
                }
                if edge_dict not in visited_edges:
                    visited_edges.append(edge_dict)

                # Add newly discovered nodes
                for nid, nname, ntype, nprops in [
                    (r["source_id"], r["source_name"], r["source_type"], r["source_props"]),
                    (r["target_id"], r["target_name"], r["target_type"], r["target_props"]),
                ]:
                    if nid not in matched_nodes:
                        matched_nodes[nid] = {
                            "id": nid,
                            "name": nname,
                            "type": ntype,
                            "properties": json.loads(nprops or "{}"),
                        }
                    if nid not in seen_nodes:
                        seen_nodes.add(nid)
                        next_frontier.add(nid)

            frontier = next_frontier

        return {
            "query": entity_query,
            "total_nodes": len(matched_nodes),
            "total_edges": len(visited_edges),
            "nodes": list(matched_nodes.values()),
            "edges": visited_edges,
        }


def format_graph_narrative(subgraph: Dict[str, Any]) -> str:
    """Format extracted subgraph into high-density prompt-ready context."""
    lines = []
    edges = subgraph.get("edges", [])
    if not edges:
        nodes = subgraph.get("nodes", [])
        return "\n".join(f"- [{n['type']}] {n['name']} (ID: {n['id']})" for n in nodes[:5])

    for e in edges:
        lines.append(f"- ({e['source_type']}: {e['source_name']}) --[{e['relation']}]--> ({e['target_type']}: {e['target_name']})")
    return "\n".join(lines[:12])
