# -*- coding: utf-8 -*-
# Copyright (C) 2017 Matthias Luescher
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

import logging
import os
from edi.commands.lxc import Lxc
from edi.lib.configurationparser import command_context
from edi.lib.lxchelpers import (export_image, get_file_extension_from_image_compression_algorithm,
                                get_server_image_compression_algorithm)
from edi.commands.lxccommands.publish import Publish
from edi.lib.helpers import print_success, get_artifact_dir, create_artifact_dir


class Export(Lxc):

    @classmethod
    def advertise(cls, subparsers):
        help_text = "export an image from the LXD image store"
        description_text = "Export an image from the LXD image store."
        parser = subparsers.add_parser(cls._get_short_command_name(),
                                       help=help_text,
                                       description=description_text)
        cls._offer_options(parser, introspection=True, clean=True)
        cls._require_config_file(parser)

    def run_cli(self, cli_args):
        self._dispatch(*self._unpack_cli_args(cli_args), run_method=self._get_run_method(cli_args))

    def dry_run(self, config_file):
        return self._dispatch(config_file, run_method=self._dry_run)

    def _dry_run(self):
        return Publish().dry_run(self.config.get_base_config_file())

    def run(self, config_file):
        return self._dispatch(config_file, run_method=self._run)

    def _run(self):
        if os.path.isfile(self._result()):
            logging.info(("{0} is already there. "
                          "Delete it to regenerate it."
                          ).format(self._result()))
            return self._result()

        image_name = Publish().run(self.config.get_base_config_file())

        print("Going to export lxc image from image store.")

        create_artifact_dir()
        export_image(image_name, self._image_without_extension())

        if (os.path.isfile(self._image_without_extension()) and
                not os.path.isfile(self._result())):
            # Workaround for https://github.com/lxc/lxd/issues/3869
            logging.info("Fixing file extension of exported image.")
            os.rename(self._image_without_extension(), self._result())

        print_success("Exported lxc image as {}.".format(self._result()))
        return self._result()

    def clean_recursive(self, config_file, depth):
        self.clean_depth = depth
        self._dispatch(config_file, run_method=self._clean)

    def clean(self, config_file):
        self._dispatch(config_file, run_method=self._clean)

    def _clean(self):
        if os.path.isfile(self._result()):
            logging.info("Removing '{}'.".format(self._result()))
            os.remove(self._result())
            print_success("Removed lxc image {}.".format(self._result()))

        if self.clean_depth > 0:
            Publish().clean_recursive(self.config.get_base_config_file(), self.clean_depth - 1)

    def _dispatch(self, config_file, run_method):
        with command_context({'edi_create_distributable_image': True}):
            self._setup_parser(config_file)
            return run_method()

    def _result_base_name(self):
        return "{0}_{1}".format(self.config.get_configuration_name(),
                                self._get_command_file_name_prefix())

    def _image_without_extension(self):
        return os.path.join(get_artifact_dir(), self._result_base_name())

    def result(self, config_file):
        return self._dispatch(config_file, run_method=self._result)

    def _result(self):
        algorithm = get_server_image_compression_algorithm()
        extension = get_file_extension_from_image_compression_algorithm(algorithm)
        archive = "{}{}".format(self._result_base_name(), extension)
        return os.path.join(get_artifact_dir(), archive)
