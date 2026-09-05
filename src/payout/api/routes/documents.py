"""Rider documents — upload, list, download, delete.

Recruiters upload KYC (Aadhaar, PAN, licence, bank proof, photo…) against a
PERSON, so a rider who works for two companies has one set of papers. The
bytes go to the document store (``payout.documents``); the row here is the
index. Every upload and delete is written to the activity log.

Routes:
  GET    /api/persons/{person_id}/documents           list
  POST   /api/persons/{person_id}/documents           upload (multipart)
  GET    /api/documents/{doc_id}/download             the file
  DELETE /api/documents/{doc_id}                      admin, or the uploader
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin, require_recruiter
from payout.db import get_connection
from payout.documents import (
    ALLOWED_CONTENT_TYPES,
    DOC_TYPES,
    MAX_DOCUMENT_BYTES,
    get_storage,
    make_key,
)
from payout.domain.activity import record_activity

person_router = APIRouter()  # mounted at /api/persons
router = APIRouter()  # mounted at /api/documents


class DocumentOut(BaseModel):
    id: int
    person_id: int
    doc_type: str
    filename: str
    content_type: str
    size_bytes: int
    notes: str | None = None
    uploaded_by: str
    uploaded_at: str | None = None


def _doc_out(row) -> DocumentOut:
    return DocumentOut(**{k: row[k] for k in DocumentOut.model_fields})


@router.get("/types")
def document_types(_: dict = Depends(get_current_user)) -> dict:
    """What the upload form may offer: document kinds, accepted file types, size cap."""
    return {
        "doc_types": list(DOC_TYPES),
        "content_types": list(ALLOWED_CONTENT_TYPES),
        "max_bytes": MAX_DOCUMENT_BYTES,
        "backend": get_storage().name,
    }


@person_router.get("/{person_id}/documents", response_model=list[DocumentOut])
def list_documents(person_id: int, _: dict = Depends(get_current_user)) -> list[DocumentOut]:
    with get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM person_registry WHERE person_id=?", (person_id,)
        ).fetchone():
            raise HTTPException(404, "Person not found")
        rows = conn.execute(
            "SELECT id, person_id, doc_type, filename, content_type, size_bytes, notes, "
            "uploaded_by, uploaded_at FROM rider_documents WHERE person_id=? "
            "ORDER BY uploaded_at DESC, id DESC",
            (person_id,),
        ).fetchall()
    return [_doc_out(r) for r in rows]


@person_router.get("/{person_id}/photo")
def person_photo(person_id: int, _: dict = Depends(get_current_user)) -> Response:
    """The rider's profile picture: the most recent 'photo' document. 404 when
    there is none, so an <img> can fall back to initials."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT content_type, storage_key FROM rider_documents "
            "WHERE person_id=? AND doc_type='photo' AND content_type LIKE 'image/%' "
            "ORDER BY id DESC LIMIT 1",
            (person_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "No photo")
    try:
        data = get_storage().get(row["storage_key"])
    except FileNotFoundError as exc:
        raise HTTPException(410, "The photo is missing from the document store") from exc
    return Response(
        content=data,
        media_type=row["content_type"],
        headers={"Cache-Control": "private, max-age=60"},
    )


@person_router.post("/{person_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    person_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    notes: str | None = Form(default=None),
    user: dict = Depends(require_recruiter),
) -> DocumentOut:
    doc_type = (doc_type or "").strip().lower()
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"doc_type must be one of {list(DOC_TYPES)}")
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            415, f"Only {', '.join(ALLOWED_CONTENT_TYPES)} are accepted (got {ctype or 'unknown'})"
        )
    if doc_type == "photo" and not ctype.startswith("image/"):
        raise HTTPException(415, "A profile photo must be a JPEG, PNG or WebP image")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            413, f"File is {len(data) // 1024} KB; the limit is {MAX_DOCUMENT_BYTES // 1024} KB"
        )
    filename = (file.filename or "document").strip()[:200]
    key = make_key(person_id, ctype)
    with get_connection() as conn:
        person = conn.execute(
            "SELECT display_name FROM person_registry WHERE person_id=?", (person_id,)
        ).fetchone()
        if not person:
            raise HTTPException(404, "Person not found")
        # Store the bytes first: if that fails there is nothing to index.
        get_storage().put(key, data, ctype)
        cur = conn.execute(
            "INSERT INTO rider_documents (person_id, doc_type, filename, content_type, "
            "size_bytes, storage_key, notes, uploaded_by) VALUES (?,?,?,?,?,?,?,?)",
            (person_id, doc_type, filename, ctype, len(data), key, notes or None, user["email"]),
        )
        doc_id = cur.lastrowid
        record_activity(
            conn,
            user,
            "document.upload",
            entity_type="document",
            entity_id=doc_id,
            label=f"{doc_type}: {filename}",
            person_id=person_id,
            details={"doc_type": doc_type, "filename": filename, "size_bytes": len(data)},
        )
        row = conn.execute(
            "SELECT id, person_id, doc_type, filename, content_type, size_bytes, notes, "
            "uploaded_by, uploaded_at FROM rider_documents WHERE id=?",
            (doc_id,),
        ).fetchone()
        conn.commit()
    return _doc_out(row)


@router.get("/{doc_id}/download")
def download_document(doc_id: int, _: dict = Depends(get_current_user)) -> Response:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT filename, content_type, storage_key FROM rider_documents WHERE id=?",
            (doc_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Document not found")
    try:
        data = get_storage().get(row["storage_key"])
    except FileNotFoundError as exc:
        raise HTTPException(410, "The file is missing from the document store") from exc
    safe_name = row["filename"].replace('"', "").replace("\n", " ")
    return Response(
        content=data,
        media_type=row["content_type"],
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.delete("/{doc_id}")
def delete_document(doc_id: int, user: dict = Depends(require_admin)) -> dict:
    """Admins only. Recruiters edit but never delete (2026-09-05 rule): a
    wrong upload is replaced by uploading the right one and asking an admin."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT person_id, doc_type, filename, storage_key, uploaded_by "
            "FROM rider_documents WHERE id=?",
            (doc_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Document not found")
        conn.execute("DELETE FROM rider_documents WHERE id=?", (doc_id,))
        record_activity(
            conn,
            user,
            "document.delete",
            entity_type="document",
            entity_id=doc_id,
            label=f"{row['doc_type']}: {row['filename']}",
            person_id=row["person_id"],
            details={"uploaded_by": row["uploaded_by"]},
        )
        conn.commit()
    get_storage().delete(row["storage_key"])
    return {"deleted": True, "id": doc_id}
