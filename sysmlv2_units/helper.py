import syside
import syside.query
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
            model_name_index: syside.query.NameIndex,
            qualified_name: str,
            kind: Type[syside.Element] = None,
            env: bool = False,
    ) -> Optional[syside.Element]:
        """
        Resolve a qualified name like "Pkg::SubPkg::ElementName".

        If `kind` is given, ensures the result is of that type.
        If `env` is True, also searches the environment (stdlib).
        """
        library_elements = syside.query.LibraryElements.ALL if env else syside.query.LibraryElements.WORKSPACE
        element = syside.query.find_by_qualified_name(
            model, qualified_name, library_elements=library_elements, index=model_name_index)

        if kind is not None:
            return element if isinstance(element, kind) else None
        return element
