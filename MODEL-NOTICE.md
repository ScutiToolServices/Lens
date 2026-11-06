# English model attribution

This service uses unmodified English traineddata files from Tesseract OCR's
official `tessdata_fast` and `tessdata_best` repositories:

- https://github.com/tesseract-ocr/tessdata_fast
- https://github.com/tesseract-ocr/tessdata_best

Upstream distributes these files under Apache License 2.0. The complete license
is included in `MODEL-LICENSE.txt` and copied into `/opt/ocr-models/LICENSE` in the
Docker image. The installer records the accepted SHA-256 hashes in `src/models.py`.

Tesseract binaries are installed separately by the host or operating-system
package manager; their package-provided license notices remain with those files.
