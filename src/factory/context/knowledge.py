#!/usr/bin/env python3
"""
Knowledge Graph
Manages knowledge graph for cross-mission learning.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from pathlib import Path
import sqlite3


@dataclass
class KnowledgeNode:
    """Node in the knowledge graph."""
    node_id: str
    node_type: str  # "file", "function", "class", "concept", "pattern"
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class KnowledgeEdge:
    """Edge in the knowledge graph."""
    edge_id: str
    source_id: str
    target_id: str
    relation_type: str  # "calls", "imports", "inherits", "references", "similar_to"
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class KnowledgeGraph:
    """Knowledge graph for cross-mission learning."""
    
    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._db_path = Path(f".knowledge_{mission_id}.db")
        self._nodes: Dict[str, KnowledgeNode] = {}
        self._edges: Dict[str, KnowledgeEdge] = {}
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                edge_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    
    async def add_node(self, node_type: str, name: str, properties: Dict[str, Any] = None) -> KnowledgeNode:
        """Add a node to the knowledge graph."""
        node_id = str(uuid.uuid4())[:8]
        node = KnowledgeNode(
            node_id=node_id,
            node_type=node_type,
            name=name,
            properties=properties or {}
        )
        self._nodes[node_id] = node
        
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO nodes (node_id, node_type, name, properties, created_at) VALUES (?, ?, ?, ?, ?)",
            (node_id, node_type, name, json.dumps(properties or {}), datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return node
    
    async def add_edge(self, source_id: str, target_id: str, relation_type: str, properties: Dict = None) -> KnowledgeEdge:
        """Add an edge between nodes."""
        edge_id = str(uuid.uuid4())[:8]
        edge = KnowledgeEdge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            properties=properties or {}
        )
        self._edges[edge_id] = edge
        
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO edges (edge_id, source_id, target_id, relation_type, properties, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (edge_id, source_id, target_id, relation_type, json.dumps(properties or {}), datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return edge
    
    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """Get a node by ID."""
        return self._nodes.get(node_id)
    
    def get_neighbors(self, node_id: str, relation_type: Optional[str] = None) -> List[KnowledgeEdge]:
        """Get neighboring edges."""
        edges = [e for e in self._edges.values() if e.source_id == node_id or e.target_id == node_id]
        if relation_type:
            edges = [e for e in edges if e.relation_type == relation_type]
        return edges
    
    def search(self, query: str, node_type: Optional[str] = None) -> List[KnowledgeNode]:
        """Search nodes by name or property."""
        results = []
        for node in self._nodes.values():
            if node_type and node.node_type != node_type:
                continue
            if query.lower() in node.name.lower() or any(query.lower() in str(v).lower() for v in node.properties.values()):
                results.append(node)
        return results


# Import required modules
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import json
import uuid
from pathlib import Path
import sqlite3