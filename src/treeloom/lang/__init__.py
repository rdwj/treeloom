"""Language plugin system: visitor protocol, base class, and registry."""

from treeloom.lang.base import TreeSitterVisitor
from treeloom.lang.protocol import LanguageVisitor, NodeEmitter
from treeloom.lang.registry import LanguageRegistry

__all__ = [
    "LanguageRegistry",
    "LanguageVisitor",
    "NodeEmitter",
    "TreeSitterVisitor",
]
