"""The suggestors for moving things around."""
from __future__ import absolute_import

import ast
import os

import khodemod
import util


def move_module_suggestor(project_root, old_fullname, new_fullname):
    """Move a module from old_fullname to new_fullname.

    old_fullname and new_fullname should be dotted names.  Their paths
    are taken to be relative to project_root.  The destination must
    not already exist.
    """
    def filename_for(mod):
        return os.path.join(project_root, util.filename_for_module_name(mod))

    def suggestor(filename, body):
        new_filename = util.filename_for_module_name(new_fullname)
        old_pathname = filename_for(old_fullname)
        new_pathname = filename_for(new_fullname)
        if (os.path.normpath(os.path.join(project_root, filename)) !=
                os.path.normpath(old_pathname)):
            return
        assert not os.path.exists(new_pathname), new_pathname

        yield khodemod.Patch(filename, body, None, 0, len(body))
        yield khodemod.Patch(new_filename, None, body, 0, 0)

    return suggestor


def move_symbol_suggestor(project_root, old_fullname, new_fullname):
    """Move a symbol from old_fullname to new_fullname.

    old_fullname and new_fullname should both be dotted names of
    the form module.symbol.  The destination fullname should not
    already exist (though the destination module may).
    """
    def suggestor(filename, body):
        try:
            file_info = util.File(filename, body)
        except Exception as e:
            raise khodemod.FatalError(filename, 0,
                                      "Couldn't parse this file: %s" % e)

        (old_module, old_symbol) = old_fullname.rsplit('.', 1)
        (new_module, new_symbol) = new_fullname.rsplit('.', 1)

        if filename != util.filename_for_module_name(old_module):
            return

        # Find where old_fullname is defined in old_module.
        # TODO(csilvers): traverse try/except, for, etc, and complain
        # if we see the symbol defined inside there.
        # TODO(csilvers): look for ast.AugAssign and complain if our
        # symbol is in there.
        old_module_toplevel = util.toplevel_names(file_info)
        if old_symbol not in old_module_toplevel:
            raise khodemod.FatalError(filename, 0,
                                      "Could not find symbol '%s' in '%s': "
                                      "maybe it's in a try/finally or if?"
                                      % (old_symbol, old_module))

        # Now get the startpos and endpos of this symbol's definition.
        node_to_move = old_module_toplevel[old_symbol]
        start, end = util.get_area_for_ast_node(
            node_to_move, file_info, include_previous_comments=True)
        definition_region = body[start:end]

        # Decide what text to add, which may require a rename.
        if old_symbol == new_symbol:
            new_definition_region = definition_region
        else:
            # Find the token with the name of the symbol, and update it.
            if isinstance(node_to_move, (ast.FunctionDef, ast.ClassDef)):
                for token in file_info.tokens.get_tokens(node_to_move):
                    if token.string in ('def', 'class'):
                        break
                else:
                    raise khodemod.FatalError(
                        filename, 0,
                        "Could not find symbol '%s' in "
                        "'%s': maybe it's defined weirdly?"
                        % (old_symbol, old_module))
                # We want the token after the def.
                name_token = file_info.tokens.next_token(token)
            else:  # isinstance(node_to_move, ast.Assign)
                # The name should be a single token, if we get here.
                name_token, = list(file_info.tokens.get_tokens(
                    node_to_move.targets[0]))

            if name_token.string != old_symbol:
                raise khodemod.FatalError(filename, 0,
                                          "Could not find symbol '%s' in "
                                          "'%s': maybe it's defined weirdly?"
                                          % (old_symbol, old_module))
            new_definition_region = (
                body[start:name_token.startpos] + new_symbol
                + body[name_token.endpos:end])

        if old_module == new_module:
            # Just patch the module in place.
            yield khodemod.Patch(
                filename, definition_region, new_definition_region, start, end)
        else:
            # Remove the region from the old file.
            # (If we've removed the remainder of the file,
            # _remove_empty_files_suggestor will clean up.)
            yield khodemod.Patch(filename, definition_region, '', start, end)

            # Add the region to the new file.
            new_filename = util.filename_for_module_name(new_module)
            new_file_body = khodemod.read_file(
                project_root, new_filename) or ''

            # Mess about with leading newlines.  First, we strip any existing
            # ones.  Then, if we are adding to an existing file, we add enough
            # to satisfy pep8.
            new_definition_region = new_definition_region.lstrip('\r\n')
            if new_file_body:
                current_newlines = (
                    len(new_file_body) - len(new_file_body.rstrip('\r\n'))
                    + len(new_definition_region)
                    - len(new_definition_region.lstrip('\r\n')))
                if current_newlines < 3:
                    new_definition_region = ('\n' * (3 - current_newlines)
                                             + new_definition_region)

            # Now we need to add the new symbol to new_module.
            # TODO(benkraft): Allow, as an option, adding it after a specific
            # other symbol in new_module.
            yield khodemod.Patch(new_filename, '', new_definition_region,
                                 len(new_file_body), len(new_file_body))

            # TODO(benkraft): Fix up imports in the new and old modules.

    return suggestor