"""Data models used across the application."""

from __future__ import annotations

from dataclasses import dataclass, field

#: Human-readable event status labels keyed by ``status_code``.
STATUS_LABELS: dict[int, str] = {
    0: "Event Created",
    1: "Upload In Progress",
    2: "Photo Uploaded",
    3: "Face Match In Progress",
    4: "Results Ready",
    5: "Whatsapp Sharing In Progress",
    6: "Event Completed",
}


@dataclass
class Event:
    """Represents a single Skyvas event."""

    id: str
    name: str
    place: str
    date: str
    event_type: str
    status_code: int
    total_photos: int = 0
    pricing_category: str = ""
    n_registrations: int = 0

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status_code, "Unknown")

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            place=data.get("place", ""),
            date=data.get("date", ""),
            event_type=data.get("type", data.get("event_type", "")),
            status_code=int(data.get("status_code", 0)),
            total_photos=int(data.get("total_photos", 0)),
            pricing_category=data.get("pricing_category", ""),
            n_registrations=int(data.get("n_registrations", 0)),
        )


@dataclass
class UploadUrl:
    """Presigned S3 upload URL returned by the API."""

    upload_url: str
    file_url: str

    @classmethod
    def from_dict(cls, data: dict) -> UploadUrl:
        return cls(
            upload_url=data["uploadUrl"],
            file_url=data["fileUrl"],
        )


@dataclass
class UploadStatus:
    """Per-event upload tracking information."""

    event_id: str
    total: int = 0
    uploaded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def progress_text(self) -> str:
        if self.total == 0:
            return "—"
        return f"{self.uploaded}/{self.total}"

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and (self.uploaded + self.failed) >= self.total
