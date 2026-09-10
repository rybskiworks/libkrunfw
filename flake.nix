{
  description = "libkrunfw — Linux kernel bundled as a shared library";

  inputs = {
    tooling.url = "github:rybskiworks/nix-tooling/eae927a0da5fd04d2dfd2e7876042c6243adba65";
    nixpkgs.follows = "tooling/nixpkgs";
    flake-parts.follows = "tooling/flake-parts";

    devenv.follows = "tooling/devenv";
    treefmt-nix.follows = "tooling/treefmt-nix";
    git-hooks.follows = "tooling/git-hooks";
    devenv-root = {
      url = "file+file:///dev/null";
      flake = false;
    };
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      imports = [ inputs.devenv.flakeModule ];
      systems = [ "x86_64-linux" ];

      perSystem =
        { system, ... }:
        let
          pkgs = import inputs.nixpkgs { inherit system; };

          # Must stay in sync with Makefile KERNEL_VERSION/SHA256 and FULL_VERSION.
          kernelVersion = "linux-6.12.109";
          kernelSha256 = "e81af28f5941db1c7f356151dfbab2ca5786c8be76474f7d42ea306cdeb445cd";
          kernelTarball = pkgs.fetchurl {
            url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/${kernelVersion}.tar.gz";
            sha256 = kernelSha256;
          };

          # Kernel + bundle build tools (mirrors README Debian/Ubuntu reqs).
          buildDeps = with pkgs; [
            gnumake
            bc
            bison
            flex
            cpio
            xz
            (python3.withPackages (pythonPackages: [ pythonPackages.pyelftools ]))
            patch
          ];

          libkrunfw = pkgs.stdenv.mkDerivation {
            pname = "libkrunfw";
            version = "5.6.1";
            src = pkgs.lib.fileset.toSource {
              root = ./.;
              fileset = pkgs.lib.fileset.unions [
                ./Makefile
                ./bin2cbundle.py
                ./scripts
                ./patches
                ./config-libkrunfw_x86_64
              ];
            };

            buildInputs = [ pkgs.elfutils ];
            nativeBuildInputs = buildDeps;

            postPatch = ''
              patchShebangs scripts
            '';

            buildPhase = ''
              runHook preBuild
              mkdir -p tarballs
              cp ${kernelTarball} tarballs/${kernelVersion}.tar.gz
              echo "${kernelSha256}  tarballs/${kernelVersion}.tar.gz" | sha256sum -c -
              make -j$NIX_BUILD_CORES
              runHook postBuild
            '';

            installPhase = ''
              runHook preInstall
              mkdir -p $out/lib
              install -m 755 libkrunfw.so.5.6.1 $out/lib/
              ln -s libkrunfw.so.5.6.1 $out/lib/libkrunfw.so.5
              ln -s libkrunfw.so.5 $out/lib/libkrunfw.so
              mkdir -p $out/share/libkrunfw
              install -m 644 ${kernelVersion}/.config $out/share/libkrunfw/kernel.config
              install -m 644 ${kernelVersion}/include/config/kernel.release $out/share/libkrunfw/kernel.release
              echo "${kernelSha256}  ${kernelVersion}.tar.gz" > $out/share/libkrunfw/kernel-source.sha256
              sha256sum patches/0*.patch > $out/share/libkrunfw/kernel-patches.sha256
              runHook postInstall
            '';
          };
        in
        {
          packages.libkrunfw = libkrunfw;
          packages.default = libkrunfw;

          _module.args.pkgs = pkgs;

          devenv.shells.default = {
            containers = pkgs.lib.mkForce { };
            imports = [
              inputs.tooling.devenvModules.base
              inputs.tooling.devenvModules.nix
            ];
            packages = buildDeps ++ [
              pkgs.elfutils
              pkgs.curl
            ];
          };

          checks.verify-source-pins = pkgs.runCommand "libkrunfw-verify-source-pins" { } ''
            grep -Fx 'KERNEL_VERSION = ${kernelVersion}' ${./Makefile}
            grep -Fx 'KERNEL_SHA256 = ${kernelSha256}' ${./Makefile}
            mkdir -p $out
            touch $out/ok
          '';

          checks.verify-clock-only =
            pkgs.runCommandCC "libkrunfw-verify-clock-only"
              {
                nativeBuildInputs = [ pkgs.gawk ];
                src = pkgs.lib.fileset.toSource {
                  root = ./.;
                  fileset = pkgs.lib.fileset.unions [
                    ./tests/clock-only
                    ./patches/0034-virtio-add-microsandbox-vm-generation-driver.patch
                  ];
                };
              }
              ''
                bash $src/tests/clock-only/run.sh
                mkdir -p $out
                touch $out/ok
              '';

          checks.verify-libkrunfw-symbols =
            pkgs.runCommand "libkrunfw-verify-symbols" { nativeBuildInputs = [ pkgs.python3 ]; }
              ''
                mkdir -p $out
                python3 ${./tests/check-library.py} ${libkrunfw}/lib/libkrunfw.so.5.6.1
                grep -Fx 'CONFIG_POWER_RESET=y' ${libkrunfw}/share/libkrunfw/kernel.config
                grep -Fx 'CONFIG_POWER_RESET_LIBKRUN=y' ${libkrunfw}/share/libkrunfw/kernel.config
                touch $out/ok
              '';

          checks.verify-poweroff-driver =
            pkgs.runCommand "libkrunfw-verify-poweroff-driver"
              {
                nativeBuildInputs = [
                  pkgs.python3
                  pkgs.stdenv.cc
                  pkgs.patch
                ];
              }
              ''
                python3 ${./tests/check-poweroff.py} \
                  --kernel-source ${kernelTarball} \
                  --patch ${./patches}/0035-power-reset-add-libkrun-x86-poweroff.patch \
                  --patch-directory ${./patches} \
                  --config ${./config-libkrunfw_x86_64}
                mkdir -p $out
                touch $out/ok
              '';
        };
    };
}
