# The label reader

What "Scan the bag" runs, on the phone itself. Nothing here is Goccio's own work; it is kept in this folder so the site
does not depend on anyone else's server staying up, and so the files can be cached for a year (the folder name changes
when they do).

| File | What it is | From | Licence |
| --- | --- | --- | --- |
| `det.onnx` | Finds the text in a photo (PP-OCRv6 small, detection) | PaddleOCR, via github.com/PT-Perkasa-Pilar-Utama/ppu-paddle-ocr-models | Apache 2.0 |
| `rec.onnx` | Reads each piece of text (PP-OCRv6 tiny, recognition) | the same | Apache 2.0 |
| `keys.txt` | The characters `rec.onnx` can write | the same | Apache 2.0 |
| `ort.wasm.min.js`, `ort-wasm-simd-threaded.mjs`, `ort-wasm-simd-threaded.wasm` | ONNX Runtime Web 1.20.1, which runs the two networks in the browser | github.com/microsoft/onnxruntime | MIT |

PaddleOCR: Copyright (c) PaddlePaddle Authors. Licensed under the Apache License, Version 2.0
(https://www.apache.org/licenses/LICENSE-2.0). ONNX Runtime: Copyright (c) Microsoft Corporation, MIT License.

The code that drives them is in `index.html` (search for "the label reader").
