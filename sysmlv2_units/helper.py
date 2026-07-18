import syside
from typing import Optional, Type

__all__ = ['SysMLHelper']


class SysMLHelper:
    """
    Class with generic helper functions.
    """

    @staticmethod
    def get_feature_by_name(element: syside.Type, name: str) -> Optional[syside.Feature]:
        for feature in element.features:
            if feature.name == name:
                return feature

    @classmethod
    def get_element_by_qualified_name(
            cls,
            model: syside.Model,
            doc_namespace_map: dict,
            qualified_name: str,
            kind: Type[syside.Element] = None,
            env: bool = False,
    ) -> Optional[syside.Element]:
        """
        Resolve a qualified name like "Pkg::SubPkg::ElementName".
        Traverses nested namespaces/packages until the final element is found.

        If `kind` is given, ensures the result is of that type.
        If `env` is True, also searches the environment (stdlib).
        """
        # Split the qualified name by '::'
        name_parts = [p.strip() for p in qualified_name.split("::") if p.strip()]
        if not name_parts:
            return None

        # Start from the root context (MODEL or ENVIRONMENT depending on env flag)
        current = cls.search_namespace(model, doc_namespace_map, name_parts[0], env=env)

        if current is None:
            return None

        # Walk down through nested parts
        for name_part in name_parts[1:]:
            found = None
            for owned in getattr(current, "owned_elements", []):
                if owned.name == name_part or (owned.short_name and owned.short_name == name_part):
                    found = owned
                    break
            if found is None:
                return None
            current = found

        # Check type if specified
        if kind and not isinstance(current, kind):
            return None

        return current

    @staticmethod
    def search_namespace(model: syside.Model, doc_namespace_map: dict, name: str, env=False) \
            -> Optional[syside.Namespace]:
        """More efficient function to search for a root namespace (e.g. package) in all documents."""

        if (name, env) in doc_namespace_map:
            return doc_namespace_map[name, env]

        for doc_mutex in (model.environment.documents if env else model.documents):
            with doc_mutex.lock() as doc:
                root_node = doc.root_node
                for namespace_node in root_node.children.elements:
                    if namespace_node.name == name:

                        doc_namespace_map[name, env] = namespace_node
                        return namespace_node
