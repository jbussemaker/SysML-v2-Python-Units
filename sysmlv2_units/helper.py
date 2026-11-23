import syside
import contextlib
import syside.query
from pathlib import Path
from typing import Optional, Type

__all__ = ['SysMLHelper']


class SysMLHelper:
    """
    Class with generic helper functions.
    """

    @staticmethod
    def get_feature_by_name(element: syside.Type, name: str) -> Optional[syside.Feature]:
        for feature in element.features.collect():
            if feature.name == name:
                return feature

    @staticmethod
    def create_name_index(model: syside.Model) -> syside.query.NameIndex:
        """
        Create the name index for `get_element_by_qualified_name`.
        """
        return syside.query.build_name_index(
            model, library_elements=syside.query.LibraryElements.ALL)

    @staticmethod
    def get_element_by_qualified_name(
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

    @staticmethod
    @contextlib.contextmanager
    def temporary_anonymous_feature(model: syside.Model):
        """
        Get a temporary anonymous feature, so you can print its feature value.
        """
        with model.documents[-1].lock() as doc:

            parent = doc.root_node
            _, feature = parent.children.append(syside.FeatureMembership, syside.Feature)

            yield feature

            parent.children.remove_element(feature)

    @staticmethod
    def create_empty_model() -> syside.Model:
        """
        Create a model with 1 empty document.
        """
        model, _ = syside.load_model([])
        model.documents.append(syside.Document.create_st(
            syside.DocumentOptions(url=syside.Url('memory://new'), language='sysml'),
        ))
        return model

    @classmethod
    def load_workspace_model(cls, workspace_dir: Path, print_diagnostics=False) -> syside.Model:
        """
        Load a model from a workspace, automatically detecting all relevant files.
        Use the `SysMLUnitsHelper.write_document` function to write to file.
        """
        files = syside.collect_files_recursively(workspace_dir)
        try:
            model, diagnostics = syside.try_load_model(files, attach_comments=True)
        except (syside.ModelError, RuntimeError):
            raise

        if print_diagnostics:
            for diag in diagnostics.all:
                print(str(diag))

        return model
