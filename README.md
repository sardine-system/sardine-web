# sardine-web

The official web editor plugin for the [sardine-system] library!

## Installation

The main repository has not yet merged CLI plugin support into the main repo.
First follow the [installation guide] in the documentation, then install Sardine
on the sardine-web-plugin branch like so:

```sh
# From remote:
pip install "git+https://github.com/Bubobubobubobubo/sardine@sardine-web-plugin"
# Or from local clone which is set to the sardine-web-plugin branch:
pip install -e <PATH_TO_REPO>
```

With Node.js / Yarn installed as per the guide, you can then install this package:

```sh
# From remote:
pip install git+https://github.com/sardine-system/sardine-web
# Or from local clone in current working directory:
pip install -e .[dev]
```

[sardine-system]: https://github.com/Bubobubobubobubo/sardine
[installation guide]: https://sardine.raphaelforment.fr/installation.html
