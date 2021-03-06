# -*- coding: utf-8 -*-
# Copyright (C) 2016 Matthias Luescher
#
# Authors:
#  Matthias Luescher
#
# This file is part of edi.
#
# edi is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# edi is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with edi.  If not, see <http://www.gnu.org/licenses/>.

from edi.lib.commandfactory import CommandFactory
from edi.lib.configurationparser import ConfigurationParser
import argparse
import os
import logging
import yaml
from functools import partial
from edi.lib.helpers import FatalError
from edi.lib.shellhelpers import run
from edi.lib.commandfactory import get_sub_commands, get_command


def compose_command_name(current_class):
    if EdiCommand is current_class:
        return EdiCommand.__name__.lower()
    else:
        assert len(current_class.__bases__) == 1
        return "{}.{}".format(compose_command_name(current_class.__bases__[0]),
                              current_class.__name__.lower())


class EdiCommand(metaclass=CommandFactory):

    def __init__(self):
        self.clean_depth = 0
        self.config = None

    def clean(self, config_file):
        pass

    def _get_sibling_commands(self):
        assert len(type(self).__bases__) == 1
        commands = []
        parent_command = type(self).__bases__[0]._get_command_name()
        for _, command in get_sub_commands(parent_command).items():
            if command != self.__class__:
                commands.append(command)
        return commands

    def _clean_siblings_and_sub_commands(self, config_file):
        for command in self._get_sibling_commands():
            command().clean(config_file)
            command().clean_sub_commands(config_file)

    def clean_sub_commands(self, config_file):
        command = self._get_sub_command("clean")
        if command:
            command().clean(config_file)

    def _setup_parser(self, config_file):
        self.config = ConfigurationParser(config_file)

    @classmethod
    def _get_command_name(cls):
        return compose_command_name(cls)

    @classmethod
    def _get_short_command_name(cls):
        return cls.__name__.lower()

    @classmethod
    def _get_command_file_name_prefix(cls):
        return cls._get_command_name().replace(".", "_")

    @classmethod
    def _add_sub_commands(cls, parser):
        title = "{} commands".format(cls._get_short_command_name())
        subparsers = parser.add_subparsers(title=title,
                                           dest="sub_command_name")

        for _, command in get_sub_commands(cls._get_command_name()).items():
            command.advertise(subparsers)

    def _run_sub_command_cli(self, cli_args):
        if not cli_args.sub_command_name:
            raise FatalError("Missing subcommand. Use 'edi --help' for help.")
        self._get_sub_command(cli_args.sub_command_name)().run_cli(cli_args)

    def _get_sub_command(self, command):
        sub_command = "{}.{}".format(self._get_command_name(),
                                     command)
        return get_command(sub_command)

    @staticmethod
    def _require_config_file(parser):
        parser.add_argument('config_file',
                            type=argparse.FileType('r', encoding='UTF-8'))

    @staticmethod
    def _offer_options(parser, introspection=False, clean=False):
        group = parser.add_mutually_exclusive_group()
        if introspection:
            group.add_argument('--dictionary', action="store_true",
                               help='dump the load time dictionary instead of running the command')
            group.add_argument('--config', action="store_true",
                               help='dump the merged configuration instead of running the command')
            group.add_argument('--plugins', action="store_true",
                               help=('dump the active plugins including their dictionaries instead of '
                                     'running the command'))
        if clean:
            group.add_argument('--clean', action="store_true",
                               help='clean the artifacts that got produced by this command')
            group.add_argument('--recursive-clean', type=int, metavar='N',
                               help='clean the artifacts that got produced by this and the preceding N commands')
        return group

    @staticmethod
    def _unpack_cli_args(cli_args):
        return [cli_args.config_file]

    def _get_run_method(self, cli_args):
        if hasattr(cli_args, 'dictionary') and cli_args.dictionary:
            return partial(self._print, self._get_load_time_dictionary)
        elif hasattr(cli_args, 'config') and cli_args.config:
            return partial(self._print, self._get_config)
        elif hasattr(cli_args, 'plugins') and cli_args.plugins:
            return partial(self._print, partial(self.dry_run, *self._unpack_cli_args(cli_args)))
        elif hasattr(cli_args, 'clean') and cli_args.clean:
            return partial(self.clean_recursive, *self._unpack_cli_args(cli_args), 0)
        elif hasattr(cli_args, 'recursive_clean') and cli_args.recursive_clean is not None:
            return partial(self.clean_recursive, *self._unpack_cli_args(cli_args), cli_args.recursive_clean)
        else:
            return partial(self.run, *self._unpack_cli_args(cli_args))

    def run(self, *args, **kwargs):
        raise FatalError('''Missing 'run' implementation for '{}'.'''.format(self._get_command_name()))

    def dry_run(self, *args, **kwargs):
        raise FatalError('''Missing 'dry_run' implementation for '{}'.'''.format(self._get_command_name()))

    def clean_recursive(self, *args, **kwargs):
        raise FatalError('''Missing 'clean_recursive' implementation for '{}'.'''.format(self._get_command_name()))

    def _get_load_time_dictionary(self):
        return self.config.get_load_time_dictionary()

    def _get_config(self):
        return self.config.get_config()

    def _get_plugins(self, sections):
        return self.config.get_plugins(sections)

    @staticmethod
    def _dump(introspection_result):
        return yaml.dump(introspection_result, default_flow_style=False, width=1000)

    def _print(self, method):
        print(self._dump(method()))

    def _require_sudo(self):
        if os.getuid() != 0:
            raise FatalError(("The subcommand '{0}' requires superuser "
                              "privileges.\n"
                              "Use 'sudo edi ...'."
                              ).format(self._get_short_command_name()))

    def _pack_image(self, tempdir, datadir, name="result"):
        # advanced options such as numeric-owner are not supported by
        # python tarfile library - therefore we use the tar command line tool
        tempresult = "{0}.tar.{1}".format(name,
                                          self.config.get_compression())
        archive_path = os.path.join(tempdir, tempresult)

        cmd = []
        cmd.append("tar")
        cmd.append("--numeric-owner")
        cmd.extend(["-C", datadir])
        cmd.extend(["-acf", archive_path])
        cmd.extend(os.listdir(datadir))
        run(cmd, sudo=True, log_threshold=logging.INFO)
        return archive_path

    def _unpack_image(self, image, tempdir, subfolder="rootfs"):
        target_folder = os.path.join(tempdir, subfolder)
        os.makedirs(target_folder, exist_ok=True)

        cmd = []
        cmd.append("tar")
        cmd.append("--numeric-owner")
        cmd.extend(["-C", target_folder])
        cmd.extend(["-axf", image])
        run(cmd, sudo=True, log_threshold=logging.INFO)
        return target_folder
