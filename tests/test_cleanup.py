import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session

from app.models import FileRecord
from app.services.cleanup import delete_expired_files


@pytest.mark.asyncio
async def test_delete_expired_files_logic(session: Session, setup_test_env: str):
    temp_dir = Path(setup_test_env)
    now = datetime.now(timezone.utc)
    
    # File 1: Pending (should be ignored)
    path1 = temp_dir / "1.mp3"
    path1.write_text("dummy")
    rec1 = FileRecord(
        filename="1.mp3",
        sha256="1",
        status="pending",
        uploaded_at=now,
        local_path=str(path1),
    )
    
    # File 2: Done, no nextcloud_path (should be ignored)
    path2 = temp_dir / "2.mp3"
    path2.write_text("dummy")
    rec2 = FileRecord(
        filename="2.mp3",
        sha256="2",
        status="done",
        uploaded_at=now,
        local_path=str(path2),
    )
    
    # File 3: Done, backed up, delete_after in future (should be ignored)
    path3 = temp_dir / "3.mp3"
    path3.write_text("dummy")
    rec3 = FileRecord(
        filename="3.mp3",
        sha256="3",
        status="done",
        uploaded_at=now,
        local_path=str(path3),
        nextcloud_path="/remote/3.mp3",
        delete_after=now + timedelta(days=1),
    )
    
    # File 4: Done, backed up, delete_after in past (should be deleted)
    path4 = temp_dir / "4.mp3"
    path4.write_text("dummy")
    rec4 = FileRecord(
        filename="4.mp3",
        sha256="4",
        status="done",
        uploaded_at=now,
        local_path=str(path4),
        nextcloud_path="/remote/4.mp3",
        delete_after=now - timedelta(days=1),
    )
    
    # File 5: Already missing locally (should log warning, not crash)
    path5 = temp_dir / "5.mp3"
    rec5 = FileRecord(
        filename="5.mp3",
        sha256="5",
        status="done",
        uploaded_at=now,
        local_path=str(path5),
        nextcloud_path="/remote/5.mp3",
        delete_after=now - timedelta(days=1),
    )
    
    session.add_all([rec1, rec2, rec3, rec4, rec5])
    session.commit()
    
    # Run cleanup
    await delete_expired_files()
    
    # Check filesystem
    assert path1.exists() is True
    assert path2.exists() is True
    assert path3.exists() is True
    assert path4.exists() is False  # Deleted!
    
    # Check DB records are preserved
    session.expire_all()
    assert session.get(FileRecord, rec4.id) is not None
    assert session.get(FileRecord, rec5.id) is not None
