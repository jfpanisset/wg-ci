# SPDX-License-Identifier: Apache-2.0
# Copyright 2023 The Foundry Visionmongers Ltd

import os
import sys
import glob
import shutil

from conans import ConanFile, tools
from conans.model.version import Version
from conans.errors import ConanException


class PySide6Conan(ConanFile):
    name = "pyside6"
    license = "LGPL-3.0"
    author = "The Qt Company"
    url = "git://code.qt.io/pyside/pyside-setup.git"
    description = "PySide6 is the official Python module from the 'Qt for Python project', which provides access to the complete Qt 6+ framework"
    settings = "os", "compiler", "build_type", "arch"
    options = {
        "shared": [True],
        "python_version": [3.9],
    }
    revision_mode = 'scm'
    package_originator = "External"
    package_exportable = True

    default_options = {"shared": True, "python_version": 3.9,
    }
    no_copy_source = True
    short_paths = True

    executables = [
        "shiboken6",
        "lupdate",
    ]

    @property
    def _useFoundryGLBackend(self):
        try: # If Qt is built with default GLBackend options this option is not present.
            return self.options["Qt"].GLBackend == "FoundryGL"
        except ConanException:
            return False

    @property
    def _useOpenGLBackend(self):
        return self.options.GLBackend == "OpenGL"

    def requirements(self):
        self.requires("Python/[~3.9.10]")
        self.requires("Qt/[~6.3.1]")

        if self._useFoundryGLBackend:
            self.requires("foundrygl/0.1@common/development")

    def build_requirements(self):
        self.build_requires("LLVM/[~13.0.1]")

        if self.settings.os == "Linux":
            self.build_requires("patchelf/0.11@thirdparty/development")

        # Windows needs separate shiboken package built in release mode due to a stack overflow
        # when running shiboken built in Debug from source (also related to libclang)
        if self.settings.os == "Windows":
            self.build_requires(f"pyside6-shiboken/{self.version}")

    def configure(self):
        self.options["Qt"].with_webengine = False
        self.options["Qt"].with_vulkan = True

    @property
    def _checkout_folder(self):
        return "{}_src".format(self.name)

    def source(self):
        version_data = self.conan_data["sources"][self.version]
        git = tools.Git(folder=self._checkout_folder)
        git.clone(version_data["git_url"])
        git.checkout(version_data["git_hash"], submodule="recursive")

    @property
    def pythonLocalRoot(self):
        # Windows uses a local copy of the Python libs, see import() for details
        return os.path.join(self.install_folder, "Python")

    def imports(self):
        if self.settings.os == "Windows":
            # Windows uses a local copy of the Python library.
            # This copy has the "Python*.zip" file removed. If this is not removed, a number of systems
            # try to load and/or modify file from this ZIP file, and fail.
            # To avoid this, we copy the Python conan package into the install directory and use it.
            self.copy(pattern="*", root_package="Python", dst=self.pythonLocalRoot, excludes="Python*.zip")

    def _set_r_paths(self, binaries, rpath=""):
        if self.settings.os == "Linux":
            if rpath != "":
                rpath = "/" + rpath
            patchelfPath = os.path.join(self.deps_cpp_info["patchelf"].bin_paths[0], "patchelf")
            for bin in binaries:
                self.run(f"{patchelfPath} --set-rpath \$ORIGIN{rpath} {bin}")
        if self.settings.os == "Macos":
            for bin in binaries:
                self.run(f"install_name_tool -add_rpath {rpath} {bin}")

    def _buildCommand(self, pythonBinPath, srcDir, qmakePath):
        # TODO Skip some modules, RemoteObjects was added by KDAB.
        # Will anyone care if these are missing?
        skipModules = ["RemoteObjects"]

        self.run(f"{pythonBinPath} -m ensurepip")

        # see https://bugreports.qt.io/browse/PYSIDE-1385 for the version choice of wheel
        index_url = "https://an_artifactory_url/artifactory/api/pypi/PyPI_Virtual/simple"
        self.run(f"{pythonBinPath} -m pip install -qq wheel==0.34.2 packaging --index-url {index_url}")

        args = [pythonBinPath, os.path.join(srcDir, "setup.py"), "build",
            "--qtpaths", qmakePath,
            "--verbose-build",
            "--skip-modules", ",".join(skipModules),
            "--make-spec", "ninja",
            "--parallel", str(tools.cpu_count()),
            "--ignore-git",
            "--reuse-build",
        ]
        if self.settings.build_type == "Debug":
            args.append("--debug")
        return " ".join(args)

    def _buildLinux(self, srcDir):
        qtInfo = self.deps_cpp_info["Qt"]
        qtBinPath = qtInfo.bin_paths[0]
        qmakePath = os.path.join(qtBinPath, "qtpaths")

        llvmInfo = self.deps_cpp_info["LLVM"]

        pythonInfo = self.deps_cpp_info["Python"]
        pythonBinPath = os.path.join(pythonInfo.rootpath, self.deps_user_info["Python"].interpreter)

        env = {
            "LLVM_INSTALL_DIR" : llvmInfo.rootpath,
            "LD_LIBRARY_PATH" : pythonInfo.lib_paths,
            "CMAKE_PREFIX_PATH": pythonInfo.rootpath,
        }

        with tools.environment_append(env):
            buildCmd = self._buildCommand(pythonBinPath, srcDir, qmakePath)
            self.run(buildCmd)

            installBinDir = os.path.join(self._installDir, "bin")

            self._set_r_paths([os.path.join(installBinDir, exe) for exe in self.executables])

            # Copy the shared libraries shiboken needs to be able to run into the package
            for lib in ("Core", "Gui", "Network", "OpenGL", "Widgets", "Xml"):
                for f in glob.glob(os.path.join(qtInfo.rootpath, "lib", f"libQt6{lib}.so*")):
                    shutil.copy(f, installBinDir)
            for f in glob.glob(os.path.join(llvmInfo.rootpath, "lib", "libclang.so*")):
                shutil.copy(f, installBinDir)

    def _buildMac(self, srcDir):
        qtInfo = self.deps_cpp_info["Qt"]
        qtBinPath = qtInfo.bin_paths[0]
        qmakePath = os.path.join(qtBinPath, "qtpaths")

        llvmInfo = self.deps_cpp_info["LLVM"]

        pythonInfo = self.deps_cpp_info["Python"]
        pythonBinPath = os.path.join(pythonInfo.rootpath, self.deps_user_info["Python"].interpreter)

        env = {
            "LLVM_INSTALL_DIR" : llvmInfo.rootpath,
            "CMAKE_PREFIX_PATH": pythonInfo.rootpath,
            "CXXFLAGS" : f"-I{pythonInfo.include_paths[0]}"
        }

        if self._useFoundryGLBackend:
            foundryglInfo = self.deps_cpp_info["foundrygl"]
            env["CMAKE_PREFIX_PATH"] += ":"+foundryglInfo.rootpath

        with tools.environment_append(env):
            buildCmd =  self._buildCommand(pythonBinPath, srcDir, qmakePath)
            self.run(buildCmd)

    def _buildWindows(self, srcDir):
        qtInfo = self.deps_cpp_info["Qt"]
        qtBinPath = qtInfo.bin_paths[0]
        qmakePath = os.path.join(qtBinPath, "qtpaths.exe")
        llvmInfo = self.deps_cpp_info["LLVM"]

        pythonBinPath = os.path.join(self.pythonLocalRoot, self.deps_user_info["Python"].interpreter)

        # from Python 3.8 DLL loading is more restrictive, disallowing PATH, see https://bugs.python.org/issue43173
        # use os.add_dll_directory to ensure Qt6.dll is available.
        os.add_dll_directory(qtBinPath)
        os.environ["PATH"] += os.pathsep + qtBinPath

        env = {
            "LLVM_INSTALL_DIR" : llvmInfo.rootpath,
            "CMAKE_PREFIX_PATH": self.pythonLocalRoot,
            "CC": "cl.exe", # pick up MSVC rather than clang from LLVM
            "CXX": "cl.exe",
        }

        with tools.environment_append(env):
            # don't run the full build in one go, as that fails in Debug builds due to a stack overflow
            # in (Debug) libclang while running shiboken - bring in a release build of shiboken to build PySide6
            # seems to be related to https://bugreports.qt.io/browse/PYSIDE-739

            buildCmd =  self._buildCommand(pythonBinPath, srcDir, qmakePath)
            self.run(buildCmd + " --build-type=shiboken6")

            shibokenInfo = self.deps_cpp_info["pyside6-shiboken"]
            installBinDir = os.path.join(self._installDir, "bin")
            for f in glob.glob(os.path.join(shibokenInfo.rootpath, "bin", "*")):
                shutil.copy(f, installBinDir)

            self.run(buildCmd + " --build-type=pyside6")

    def build(self):
        srcDir = os.path.join(self.source_folder, self._checkout_folder)
        if self.settings.os == "Linux":
            self._buildLinux(srcDir)
        elif self.settings.os == "Macos":
            self._buildMac(srcDir)
        elif self.settings.os == "Windows":
            self._buildWindows(srcDir)
        else:
            raise RuntimeError("Recipe not implemented for this OS")

    @property
    def _installDir(self):
        v = tools.Version(self.deps_cpp_info["Python"].version)
        qtVersion = self.deps_cpp_info["Qt"].version

        src_dir = os.path.join(self.source_folder, self._checkout_folder)

        # pyside is using the venv name to contain the install dir.
        # see https://a_gitlab_url/libraries/conan/thirdparty/pyside/pyside/-/commit/0a40ebb1
        venv_name = os.path.basename(sys.prefix)
        if self.settings.build_type == "Debug":
            venv_name = f"{venv_name}dp"
        install_dir = os.path.join(src_dir, 'build', venv_name, 'install')
        if not os.path.isdir(install_dir):
            raise ConanException(f"Could not find the install directory {install_dir}")

        return install_dir

    def _configure_package_mac(self):
        self._set_r_paths(
            [os.path.join(self.package_folder, 'bin', exe) for exe in self.executables],
            '@executable_path'
        )

        # Copy the DLLs shiboken needs to be able to run into the package
        for lib in ("Core", "Gui", "Network", "OpenGL", "Qml", "Widgets", "Xml"):
            framework = f"Qt{lib}.framework"
            self.copy(src=os.path.join(self.deps_cpp_info["Qt"].lib_paths[0], framework), pattern='*', dst=f'bin/{framework}')
            self.copy(src=os.path.join(self.deps_cpp_info["Qt"].lib_paths[0], framework), pattern='*', dst=f'lib/{framework}')

        self.copy(src=os.path.join(self.deps_cpp_info["LLVM"].rootpath, "lib"), pattern="libclang.dylib", dst='bin')

        def _getFilesByExt(searchDir, ext):
            files = []
            for file in os.listdir(searchDir):
                fullFilePath = os.path.join(searchDir, file)
                if not os.path.islink(fullFilePath) and file.endswith(ext):
                    files.append(fullFilePath)
            return files

        libDir = os.path.join(self.package_folder, 'lib')
        libs = _getFilesByExt(libDir, '.dylib')
        self._set_r_paths(libs, '@loader_path/../bin')

        v = tools.Version(self.deps_cpp_info["Python"].version)
        sitePkgDir = os.path.join(self.package_folder, f'lib/python{v.major}.{v.minor}/site-packages')

        libDir = os.path.join(self.package_folder, sitePkgDir, 'shiboken6')
        libs = _getFilesByExt(libDir, '.so')
        self._set_r_paths(libs, '@loader_path/../../../')

        libDir = os.path.join(self.package_folder, sitePkgDir, 'PySide6')
        libs = _getFilesByExt(libDir, '.so')
        self._set_r_paths(libs, '@loader_path/../../../')
        self._set_r_paths(libs, '@loader_path/../../../../bin')

    def package(self):
        self.copy(pattern="*", src=self._installDir, symlinks=True)
        self.copy(pattern="*", src="cmake", dst="cmake")

        if self.settings.os == 'Macos':
            self._configure_package_mac()

        # Shiboken needs LLVM available on Linux to be able to determine
        # system include paths while parsing. For simplicity, just copying
        # the whole package into this one.
        if self.settings.os == "Linux":
            self.copy(pattern="*", src=self.deps_cpp_info["LLVM"].rootpath, dst="llvm")

    def package_info(self):
        v = tools.Version(self.deps_cpp_info["Python"].version)
        if self.settings.os == "Windows":
            self.user_info.site_package = os.path.join(self.package_folder, 'lib/site-packages')
        else:
            self.user_info.site_package = os.path.join(self.package_folder, f'lib/python{v.major}.{v.minor}/site-packages')