# DRAFT — unvalidated (no nix in authoring env); validate with nix flake check + nix build on a nix host
{
  description = "libkrunfw — Linux kernel bundled as a shared library (nix draft)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/a799d3e3886da994fa307f817a6bc705ae538eeb";

    # Shared tooling pin (mirrors workestrate); follows the consumer nixpkgs.
    tooling = {
      url = "github:rybskiworks/nix-tooling/18f8b85f6777240a0ecef4e93ebee69313802aed";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    flake-parts = {
      url = "github:hercules-ci/flake-parts/9d0d87172c374f89da73c1cfe6d81ae62feac1f1";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [ "x86_64-linux" ];

      perSystem =
        { system, ... }:
        let
          pkgs = import inputs.nixpkgs { inherit system; };

          kernelVersion = "linux-6.12.108";
          kernelSha256 = "c4127aa9614a6a829c537cff96a58da634a5f8cfd1aed9d1ba076d3b3a80891a";
          kernelTarball = pkgs.fetchurl {
            url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/${kernelVersion}.tar.gz";
            sha256 = kernelSha256;
          };

          # Kernel + bundle build tools (mirrors README Debian/Ubuntu reqs).
          buildDeps = with pkgs; [
            gcc
            gnumake
            bc
            bison
            flex
            elfutils
            cpio
            xz
            python3
            python3Packages.pyelftools
            patch
          ];

          libkrunfw = pkgs.stdenv.mkDerivation {
            pname = "libkrunfw";
            version = "5.6.1";
            src = ./.;

            # DRAFT: same list in both attrs while unvalidated (native
            # x86_64-linux build, so either takes effect); tidy on a nix host.
            buildInputs = buildDeps;
            nativeBuildInputs = buildDeps;

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
              runHook postInstall
            '';
          };
        in
        {
          packages.libkrunfw = libkrunfw;
          packages.default = libkrunfw;

          devShells.default = pkgs.mkShell {
            packages = buildDeps;
            shellHook = ''
              echo "libkrunfw nix draft shell (unvalidated — see flake.nix header)"
            '';
          };

          checks.verify-libkrunfw-symbols = pkgs.runCommand "libkrunfw-verify-symbols"
            { nativeBuildInputs = [ pkgs.binutils ]; }
            ''
              mkdir -p $out
              so=${libkrunfw}/lib/libkrunfw.so.5.6.1
              test -f "$so"
              (nm -D "$so" | grep -q krunfw_get_version || strings "$so" | grep -q krunfw_get_version)
              touch $out/ok
            '';
        };
    };
}
