# tahdeed data branch

This branch holds the files that `tahdeed fetch` downloads: the gazetteer (`gazetteer.sqlite`), the
trained ranker (`ranker.npz`) and `MANIFEST.json` with their SHA-256 values. It has no shared history
with the code branches.

The gazetteer is derived from OpenStreetMap and is available under the Open Database License (ODbL)
1.0. See `NOTICE.md`. The ranker was trained on the gazetteer in this branch, so use the two together.

```
tahdeed fetch
```
