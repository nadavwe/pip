import logging
from optparse import Values
from typing import Any, Iterable, List, Optional, Union

from pip._vendor.packaging.version import LegacyVersion, Version

from pip._internal.cli import cmdoptions
from pip._internal.cli.req_command import IndexGroupCommand
from pip._internal.cli.status_codes import ERROR, SUCCESS
from pip._internal.commands.search import print_dist_installation_info
from pip._internal.exceptions import CommandError, DistributionNotFound, PipError
from pip._internal.index.collector import LinkCollector
from pip._internal.index.package_finder import PackageFinder
from pip._internal.models.selection_prefs import SelectionPreferences
from pip._internal.models.target_python import TargetPython
from pip._internal.network.session import PipSession
from pip._internal.utils.misc import write_output

logger = logging.getLogger(__name__)


class IndexCommand(IndexGroupCommand):
    """
    Inspect information available from package indexes.
    """

    usage = """
        %prog versions <package>
        %prog latest <packages>
    """

    def add_options(self) -> None:
        cmdoptions.add_target_python_options(self.cmd_opts)

        self.cmd_opts.add_option(cmdoptions.ignore_requires_python())
        self.cmd_opts.add_option(cmdoptions.pre())
        self.cmd_opts.add_option(cmdoptions.no_binary())
        self.cmd_opts.add_option(cmdoptions.only_binary())

        index_opts = cmdoptions.make_option_group(
            cmdoptions.index_group,
            self.parser,
        )

        self.parser.insert_option_group(0, index_opts)
        self.parser.insert_option_group(0, self.cmd_opts)

    def run(self, options: Values, args: List[Any]) -> int:
        handlers = {
            "versions": self.get_available_package_versions,
            "latest": self.get_latest_version,
        }

        logger.warning(
            "pip index is currently an experimental command. "
            "It may be removed/changed in a future release "
            "without prior warning."
        )

        # Determine action
        if not args or args[0] not in handlers:
            logger.error(
                "Need an action (%s) to perform.",
                ", ".join(sorted(handlers)),
            )
            return ERROR

        action = args[0]

        # Error handling happens here, not in the action-handlers.
        try:
            handlers[action](options, args[1:])
        except PipError as e:
            logger.error(e.args[0])
            return ERROR

        return SUCCESS

    def _build_package_finder(
            self,
            options: Values,
            session: PipSession,
            target_python: Optional[TargetPython] = None,
            ignore_requires_python: Optional[bool] = None,
    ) -> PackageFinder:
        """
        Create a package finder appropriate to the index command.
        """
        link_collector = LinkCollector.create(session, options=options)

        # Pass allow_yanked=False to ignore yanked versions.
        selection_prefs = SelectionPreferences(
            allow_yanked=False,
            allow_all_prereleases=options.pre,
            ignore_requires_python=ignore_requires_python,
        )

        return PackageFinder.create(
            link_collector=link_collector,
            selection_prefs=selection_prefs,
            target_python=target_python,
        )

    def get_available_package_versions(self, options: Values, args: List[Any]) -> None:
        if len(args) != 1:
            raise CommandError('You need to specify exactly one argument')

        target_python = cmdoptions.make_target_python(options)
        query = args[0]

        with self._build_session(options) as session:
            finder = self._build_package_finder(
                options=options,
                session=session,
                target_python=target_python,
                ignore_requires_python=options.ignore_requires_python,
            )

            formatted_versions = self._get_versions(finder, options, query)
            latest = formatted_versions[0]

        write_output('{} ({})'.format(query, latest))
        write_output('Available versions: {}'.format(
            ', '.join(formatted_versions)))
        print_dist_installation_info(query, latest)

    def get_latest_version(self, options: Values, args: List[Any]) -> None:
        if not args:
            raise CommandError('You need to specify at least one argument')

        target_python = cmdoptions.make_target_python(options)

        with self._build_session(options) as session:
            finder = self._build_package_finder(
                options=options,
                session=session,
                target_python=target_python,
                ignore_requires_python=options.ignore_requires_python,
            )

            for package in args:
                formatted_versions = self._get_versions(finder, options, package)
                latest = formatted_versions[0]
                write_output('{}=={}'.format(package, latest))

    def _get_versions(self, finder, options, package):
        versions: Iterable[Union[LegacyVersion, Version]] = (
            candidate.version
            for candidate in finder.find_all_candidates(package)
        )

        if not options.pre:
            # Remove prereleases
            versions = (version for version in versions
                        if not version.is_prerelease)
        versions = set(versions)

        if not versions:
            raise DistributionNotFound(
                'No matching distribution found for {}'.format(package))

        formatted_versions = [str(ver) for ver in sorted(
            versions, reverse=True)]
        return formatted_versions
