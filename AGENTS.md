## Checkout the document from aqua repository

The document of aqua is hosted at <https://github.com/aquaproj/aqua>.
So please checkout the repository and refer the document.

```sh
mkdir -p .ai
if [ ! -d .ai/aqua ]; then
  git clone https://github.com/aquaproj/aqua .ai/aqua
fi
git -C .ai/aqua pull --ff-only origin main
```

Then please see .ai/aqua/website/docs.
Especially, about the registry settings, please see .ai/aqua/website/docs/reference/registry-config/\*.md.

JSON Schema:

- registry.yaml: .ai/aqua/json-schema/registry.json

The link to the document <https://aquaproj.github.io/docs/>... can be found at .ai/aqua/website/docs/...
If the document includes a link to <https://aquaproj.github.io/docs/>, please look at .ai/aqua/website/docs/...
