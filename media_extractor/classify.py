from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_CATEGORY_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "imageExt": (
        ".jpeg",
        ".jfif",
        ".tiff",
        ".jpg",
        ".exif",
        ".gif",
        ".bmp",
        ".png",
        ".ppm",
        ".pgm",
        ".pbm",
        ".pnm",
        ".webp",
        ".heif",
    ),
    "docExt": (
        ".abw",
        ".acl",
        ".afp",
        ".ami",
        ".ans",
        ".asc",
        ".aww",
        ".ccf",
        ".csv",
        ".cwk",
        ".dbk",
        ".dita",
        ".doc",
        ".docm",
        ".docx",
        ".xlsx",
        ".accdb",
        ".dot",
        ".dotx",
        ".dwd",
        ".egt",
        ".epub",
        ".ezw",
        ".fdx",
        ".ftm",
        ".ftx",
        ".gdoc",
        ".html",
        ".hwp",
        ".hwpml",
        ".log",
        ".lwp",
        ".mbp",
        ".md",
        ".me",
        ".mcw",
        ".mobi",
        ".nb",
        ".nbp",
        ".neis",
        ".odm",
        ".odoc",
        ".odt",
        ".osheet",
        ".ott",
        ".omm",
        ".pages",
        ".pub",
        ".pap",
        ".pdax",
        ".pdf",
        ".pptx",
        ".quox",
        ".rtf",
        ".rpt",
        ".sdw",
        ".se",
        ".stw",
        ".sxw",
        ".tex",
        ".info",
        ".troff",
        ".txt",
        ".uof",
        ".uoml",
        ".via",
        ".wpd",
        ".wps",
        ".wpt",
        ".wrd",
        ".wrf",
        ".wri",
        ".xhtml",
        ".xml",
        ".xps",
    ),
    "videoExt": (
        ".mxf",
        ".3g2",
        ".3gp",
        ".svi",
        ".m4v",
        ".mpg",
        ".mpeg",
        ".m2v",
        ".mp2",
        ".mpe",
        ".mpv",
        ".webm",
        ".vob",
        ".drc",
        ".flv",
        ".mkv",
        ".ogv",
        ".ogg",
        ".avi",
        ".mng",
        ".gifv",
        ".mts",
        ".m2ts",
        ".ts",
        ".mov",
        ".qt",
        ".rmvb",
        ".wmv",
        ".yuv",
        ".asf",
        ".amv",
        ".mp4",
        ".m4p",
        ".rm",
        ".roq",
        ".nsv",
        ".f4v",
        ".f4p",
        ".f4a",
        ".f4b",
    ),
    "audioExt": (
        ".aa",
        ".aax",
        ".aac",
        ".act",
        ".aiff",
        ".alac",
        ".amr",
        ".au",
        ".awd",
        ".dss",
        ".dvf",
        ".flac",
        ".gsm",
        ".ivs",
        ".m4a",
        ".m4b",
        ".m4p",
        ".mmf",
        ".movpkg",
        ".mp3",
        ".msv",
        ".mpc",
        ".nmf",
        ".ogg",
        ".raw",
        ".voc",
        ".vox",
        ".wav",
        ".wma",
        ".wv",
        ".webm",
        ".8svx",
        ".cda",
    ),
}


def normalize_extension(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower().strip()
    if not lowered:
        return None
    return lowered if lowered.startswith(".") else f".{lowered}"


class FileClassifier:
    def __init__(
        self,
        category_extensions: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        source = category_extensions or DEFAULT_CATEGORY_EXTENSIONS
        self._category_extensions = {
            category: {
                normalized
                for extension in extensions
                for normalized in [normalize_extension(extension)]
                if normalized is not None
            }
            for category, extensions in source.items()
        }

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(self._category_extensions.keys())

    def extension_of(self, path: Path) -> str | None:
        return normalize_extension(path.suffix)

    def classify(self, path: Path) -> str | None:
        extension = self.extension_of(path)
        if extension is None:
            return None
        for category, extensions in self._category_extensions.items():
            if extension in extensions:
                return category
        return None