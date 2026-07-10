#!/usr/bin/env python3
"""
Oneiros Client — a Python client for the Oneiros dream-journaling API.

Includes a full recovery phase: create encrypted backups via a BIP-39 mnemonic
phrase, and restore dreams from that phrase on any device.

Usage:
    # Interactive mode (recommended)
    python scripts/oneiros_client.py

    # Or import and use programmatically:
    from oneiros_client import OneirosClient

    client = OneirosClient()
    client_id = client.register()
    dream = client.create_dream("I was flying over a city at night...")
    # ... dialogue, analysis, backup, restore, etc.

Requirements:
    pip install httpx
"""

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger("oneiros_client")

# ──────────────────────────────────────────────
#  Config
# ──────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8000"
CLIENT_ID_FILE = Path.home() / ".oneiros" / "client_id"
PHRASE_FILE = Path.home() / ".oneiros" / "recovery_phrase.txt"


# ──────────────────────────────────────────────
#  Exceptions
# ──────────────────────────────────────────────


class OneirosError(Exception):
    """Base exception for Oneiros client errors."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        self.status_code = status_code
        self.body = body
        super().__init__(message)


class AuthenticationError(OneirosError):
    """Client not registered or unknown."""


class RateLimitError(OneirosError):
    """Rate limit exceeded."""


class PaymentRequiredError(OneirosError):
    """Pro tier required for this operation."""


# ──────────────────────────────────────────────
#  Client
# ──────────────────────────────────────────────


@dataclass
class Dream:
    id: str
    title: str | None
    body: str
    created_at: datetime
    analyzed_at: datetime | None
    analysis: dict | None
    extraction: dict | None
    image_url: str | None
    tags: list[str]
    mood: str | None
    dialogue_state: dict | None = None

    @classmethod
    def from_api(cls, data: dict) -> "Dream":
        return cls(
            id=data["id"],
            title=data.get("title"),
            body=data["body"],
            created_at=datetime.fromisoformat(data["createdAt"]),
            analyzed_at=datetime.fromisoformat(data["analyzedAt"]) if data.get("analyzedAt") else None,
            analysis=data.get("analysis"),
            extraction=data.get("extraction"),
            image_url=data.get("imageUrl"),
            tags=data.get("tags") or [],
            mood=data.get("mood"),
            dialogue_state=data.get("dialogueState"),
        )


class OneirosClient:
    """High-level client for the Oneiros API.

    Manages client identity (persisted to ~/.oneiros/client_id),
    provides typed methods for every endpoint, and implements the
    full recovery phase (backup/restore via mnemonic phrase).
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        client_id: str | None = None,
        auto_register: bool = True,
        persist: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.persist = persist
        self._http = httpx.Client(base_url=self.base_url, timeout=30.0)

        # Resolve client identity
        self.client_id: str | None = client_id
        if self.client_id is None and persist:
            self.client_id = self._load_client_id()

        if self.client_id is None and auto_register:
            self.register()

    # ── Identity persistence ──────────────────

    def _ensure_dir(self) -> Path:
        path = CLIENT_ID_FILE.parent
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_client_id(self) -> str | None:
        try:
            if CLIENT_ID_FILE.exists():
                return CLIENT_ID_FILE.read_text().strip()
        except OSError:
            pass
        return None

    def _save_client_id(self) -> None:
        if not self.persist:
            return
        self._ensure_dir()
        CLIENT_ID_FILE.write_text(self.client_id)

    def save_recovery_phrase(self, phrase_words: list[str]) -> None:
        """Persist the recovery mnemonic to ~/.oneiros/recovery_phrase.txt."""
        if not self.persist:
            return
        self._ensure_dir()
        PHRASE_FILE.write_text(" ".join(phrase_words))
        logger.info("Recovery phrase saved to %s", PHRASE_FILE)

    def load_recovery_phrase(self) -> str | None:
        """Load a previously saved recovery phrase."""
        try:
            if PHRASE_FILE.exists():
                return PHRASE_FILE.read_text().strip()
        except OSError:
            pass
        return None

    # ── Low-level request helpers ─────────────

    def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """Make an authenticated request. Raises typed exceptions on errors."""
        headers = kwargs.pop("headers", {})
        if self.client_id:
            headers["X-Client-Id"] = self.client_id

        try:
            resp = self._http.request(method, path, headers=headers, **kwargs)
        except httpx.RequestError as e:
            raise OneirosError(f"Request failed: {e}") from e

        if resp.status_code == 401:
            raise AuthenticationError(
                "Client not registered. Call register() first.",
                status_code=401,
                body=resp.text,
            )
        if resp.status_code == 402:
            raise PaymentRequiredError(
                resp.json().get("detail", "Payment required"),
                status_code=402,
                body=resp.json(),
            )
        if resp.status_code == 429:
            raise RateLimitError(
                "Rate limit exceeded. Slow down.",
                status_code=429,
                body=resp.text,
            )
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise OneirosError(
                f"API error ({resp.status_code}): {detail}",
                status_code=resp.status_code,
                body=detail,
            )

        return resp

    def _get(self, path: str, **kwargs) -> Any:
        return self._request("GET", path, **kwargs).json()

    def _post(self, path: str, **kwargs) -> Any:
        return self._request("POST", path, **kwargs).json()

    def _delete(self, path: str, **kwargs) -> None:
        self._request("DELETE", path, **kwargs)

    def _stream_sse(self, path: str, **kwargs):
        """Stream Server-Sent Events from a GET endpoint."""
        headers = kwargs.pop("headers", {})
        if self.client_id:
            headers["X-Client-Id"] = self.client_id

        with self._http.stream("GET", path, headers=headers, **kwargs) as resp:
            if resp.status_code >= 400:
                raise OneirosError(
                    f"SSE stream error ({resp.status_code})",
                    status_code=resp.status_code,
                )
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])

    # ── Health ────────────────────────────────

    def health(self) -> dict:
        """Check API health."""
        return self._get("/health")

    # ── Client Registration ───────────────────

    def register(self, client_id: str | None = None) -> str:
        """Register (or re-register) a client. Returns the client_id.

        If no client_id is given, generates a new UUID4.
        Persists the client_id locally for future sessions.
        """
        if client_id is None:
            client_id = str(uuid.uuid4())

        data = self._post("/clients", json={"client_id": client_id})
        self.client_id = data["client_id"]
        self._save_client_id()
        logger.info("Registered client: %s (tier=%s)", self.client_id, data.get("tier"))
        return self.client_id

    # ── Dreams CRUD ───────────────────────────

    def create_dream(self, body: str, title: str | None = None) -> Dream:
        """Record a new dream."""
        payload: dict[str, Any] = {"body": body}
        if title:
            payload["title"] = title
        data = self._post("/dreams", json=payload)
        return Dream.from_api(data["dream"])

    def list_dreams(self) -> list[Dream]:
        """List all dreams for this client."""
        data = self._get("/dreams")
        return [Dream.from_api(d) for d in data["dreams"]]

    def get_dream(self, dream_id: str) -> Dream:
        """Get a single dream by ID."""
        data = self._get(f"/dreams/{dream_id}")
        return Dream.from_api(data["dream"])

    def delete_dream(self, dream_id: str) -> None:
        """Delete a dream by ID."""
        self._delete(f"/dreams/{dream_id}")

    # ── Dialogue ──────────────────────────────

    def dialogue_turn(self, dream_id: str, message: str) -> list[dict]:
        """Send a message in the dialogue for a dream. Returns SSE events.

        The last event will have type='done' with turn counts.
        """
        events = []
        with self._http.stream(
            "POST",
            f"{self.base_url}/dreams/{dream_id}/dialogue",
            json={"message": message},
            headers={"X-Client-Id": self.client_id},
        ) as resp:
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                raise OneirosError(
                    f"Dialogue error ({resp.status_code}): {detail}",
                    status_code=resp.status_code,
                    body=detail,
                )
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events

    def complete_dialogue(self, dream_id: str) -> str:
        """Mark dialogue as complete. Returns the groundedAt timestamp."""
        data = self._post(f"/dreams/{dream_id}/dialogue/complete")
        return data["groundedAt"]

    # ── Analysis ──────────────────────────────

    def analyze_dream(self, dream_id: str) -> dict:
        """Stream analysis for a dream. Returns the final analysis object.

        Prints progress to stderr. The final 'done' event contains the
        full analysis under the 'analysis' key.
        """
        final_analysis = None
        for event in self._stream_sse(f"/dreams/{dream_id}/analyze"):
            etype = event.get("type")
            if etype == "token":
                # Print tokens to stderr so they don't pollute stdout
                print(event.get("value", ""), end="", file=sys.stderr, flush=True)
            elif etype == "done":
                final_analysis = event.get("analysis")
                print(file=sys.stderr)  # newline after tokens
            elif etype == "error":
                raise OneirosError(f"Analysis error: {event.get('message')}")

        if final_analysis is None:
            raise OneirosError("Analysis stream ended without a 'done' event.")
        return final_analysis

    # ── Image Generation (Pro) ────────────────

    def generate_image(self, dream_id: str) -> str:
        """Generate an image for a dream (Pro tier required). Returns the image URL."""
        data = self._post(f"/dreams/{dream_id}/image")
        return data["imageUrl"]

    # ══════════════════════════════════════════
    #  RECOVERY PHASE
    # ══════════════════════════════════════════

    def create_backup(self) -> list[str]:
        """Create an encrypted backup of all dreams.

        Returns the BIP-39 mnemonic phrase as a list of words.
        Saves the phrase to ~/.oneiros/recovery_phrase.txt automatically.

        WARNING: The mnemonic is the ONLY way to restore your data.
        Save it somewhere safe. Oneiros does NOT store it.
        """
        data = self._post("/sync/init")
        phrase_words: list[str] = data["phrase"]
        encrypted_payload: str = data["encryptedPayload"]

        # Persist locally
        self.save_recovery_phrase(phrase_words)

        logger.info(
            "Backup created. %d dreams encrypted. Recovery phrase (%d words) saved.",
            len(encrypted_payload),  # not the count, but we log it
            len(phrase_words),
        )

        return phrase_words

    def restore_from_backup(self, phrase: str | list[str] | None = None) -> list[Dream]:
        """Restore dreams from a recovery phrase.

        Args:
            phrase: The mnemonic phrase as a string, list of words, or None.
                    If None, attempts to load from ~/.oneiros/recovery_phrase.txt.

        Returns:
            The list of restored Dream objects.

        Raises:
            OneirosError: If no backup is found for the phrase, or decryption fails.
        """
        # Resolve phrase
        if phrase is None:
            loaded = self.load_recovery_phrase()
            if loaded is None:
                raise OneirosError(
                    "No recovery phrase provided and no saved phrase found. "
                    "Pass a phrase or save one with save_recovery_phrase()."
                )
            phrase = loaded

        if isinstance(phrase, list):
            phrase = " ".join(phrase)

        phrase_words = phrase.split()

        data = self._post("/sync/restore", json={"phrase": phrase_words})

        restored_client_id = data.get("client_id")
        dreams_data = data.get("dreams", [])

        # If this client isn't registered yet, register with the restored client_id
        if self.client_id is None and restored_client_id:
            logger.info("Registering with restored client_id: %s", restored_client_id)
            self.register(client_id=restored_client_id)
        elif self.client_id and restored_client_id and self.client_id != restored_client_id:
            logger.warning(
                "Restored client_id (%s) differs from current (%s). "
                "You may want to register the restored ID.",
                restored_client_id,
                self.client_id,
            )

        dreams = [Dream.from_api(d) for d in dreams_data]
        logger.info("Restored %d dreams from recovery phrase.", len(dreams))
        return dreams

    # ── Full recovery workflow ────────────────

    def full_backup_workflow(self) -> dict:
        """Run the complete backup workflow.

        Returns a dict with the recovery phrase and dream count.
        """
        dreams = self.list_dreams()
        print(f"\n📦 Backing up {len(dreams)} dream(s)...")

        phrase_words = self.create_backup()

        print(f"\n🔐 Recovery Phrase ({len(phrase_words)} words):")
        print("─" * 50)
        print(" ".join(phrase_words))
        print("─" * 50)
        print("\n⚠️  WRITE THIS DOWN. Store it somewhere safe.")
        print("   Oneiros does NOT store this phrase.")
        print("   You need it to restore your data on another device.\n")

        return {
            "phrase": " ".join(phrase_words),
            "phrase_words": phrase_words,
            "dream_count": len(dreams),
        }

    def full_restore_workflow(self, phrase: str | None = None) -> list[Dream]:
        """Run the complete restore workflow.

        Prompts for a phrase if not provided and no saved phrase exists.
        """
        if phrase is None:
            saved = self.load_recovery_phrase()
            if saved:
                print(f"📂 Found saved recovery phrase: {saved[:20]}...")
                use_saved = input("Use saved phrase? [Y/n]: ").strip().lower()
                if use_saved in ("", "y", "yes"):
                    phrase = saved

        if phrase is None:
            phrase = input("🔑 Enter your 12-word recovery phrase: ").strip()

        print("\n🔄 Restoring from backup...")
        dreams = self.restore_from_backup(phrase)
        print(f"\n✅ Restored {len(dreams)} dream(s)!\n")

        for d in dreams:
            title = d.title or "(untitled)"
            print(f"  • {d.id[:20]:20s} {title[:40]:40s} {d.created_at.date()}")

        return dreams

    # ── Cleanup ───────────────────────────────

    def close(self):
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ══════════════════════════════════════════════
#  Interactive CLI
# ══════════════════════════════════════════════


def _clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def _print_header():
    print("╔══════════════════════════════════════════╗")
    print("║        🌙  Oneiros Client  🌙           ║")
    print("║     Dream Journaling + Jungian Analysis  ║")
    print("╚══════════════════════════════════════════╝")
    print()


def _print_menu(client: OneirosClient):
    print(f"Client ID: {client.client_id[:16]}...")
    print()
    print("  [1]  Register / Identify")
    print("  [2]  Record a Dream")
    print("  [3]  List Dreams")
    print("  [4]  View Dream Details")
    print("  [5]  Dialogue with a Dream")
    print("  [6]  Complete Dialogue & Analyze")
    print("  [7]  Delete a Dream")
    print()
    print("  ── Recovery Phase ──")
    print("  [8]  Create Backup (encrypt + mnemonic)")
    print("  [9]  Restore from Backup")
    print()
    print("  [h]  Health Check")
    print("  [q]  Quit")
    print()


def _select_dream(client: OneirosClient, prompt: str = "Select dream") -> str | None:
    dreams = client.list_dreams()
    if not dreams:
        print("  (no dreams yet)")
        return None

    print()
    for i, d in enumerate(dreams, 1):
        title = d.title or "(untitled)"
        preview = d.body[:60].replace("\n", " ")
        print(f"  [{i}] {title}")
        print(f"       {preview}...")
    print()

    try:
        choice = int(input(f"  {prompt} [1-{len(dreams)}]: ").strip())
        if 1 <= choice <= len(dreams):
            return dreams[choice - 1].id
    except (ValueError, IndexError):
        pass
    return None


def _run_interactive():
    """Run the interactive CLI."""
    client = OneirosClient(persist=True)

    _clear_screen()
    _print_header()

    print(f"🔑 Client: {client.client_id}")
    print()

    while True:
        _print_menu(client)
        cmd = input("  ⚡ Choose an option: ").strip().lower()

        try:
            if cmd == "1" or cmd == "register":
                cid = input("  Client ID (blank for new): ").strip()
                client.register(cid if cid else None)
                print(f"  ✅ Registered: {client.client_id}")

            elif cmd == "2" or cmd == "record":
                print("\n  📝 Enter your dream (Ctrl+D or '---' on its own line to finish):")
                lines = []
                while True:
                    try:
                        line = input()
                        if line.strip() == "---":
                            break
                        lines.append(line)
                    except EOFError:
                        break
                body = "\n".join(lines).strip()
                if body:
                    title = input("  Title (optional): ").strip() or None
                    dream = client.create_dream(body, title)
                    print(f"\n  ✅ Dream recorded: {dream.id}")
                else:
                    print("  ⚠️  Empty dream, not saved.")

            elif cmd == "3" or cmd == "list":
                dreams = client.list_dreams()
                if not dreams:
                    print("  📭 No dreams yet.")
                else:
                    print(f"\n  📚 {len(dreams)} dream(s):\n")
                    for d in dreams:
                        title = d.title or "(untitled)"
                        analyzed = "✅" if d.analyzed_at else "⏳"
                        print(f"  {analyzed} {d.id[:20]:20s} {title[:40]:40s} {d.created_at.date()}")

            elif cmd == "4" or cmd == "view":
                dream_id = _select_dream(client, "View dream")
                if not dream_id:
                    continue
                d = client.get_dream(dream_id)
                print(f"\n  ── {d.title or 'Untitled'} ──")
                print(f"  ID:    {d.id}")
                print(f"  Date:  {d.created_at}")
                print(f"  Mood:  {d.mood or '—'}")
                print(f"  Tags:  {', '.join(d.tags) if d.tags else '—'}")
                print(f"  Image: {d.image_url or '—'}")
                print(f"\n  {d.body}\n")
                if d.analysis:
                    print(f"  Analysis:")
                    for k, v in d.analysis.items():
                        if isinstance(v, str):
                            print(f"    {k}: {v[:100]}")
                        elif isinstance(v, list):
                            print(f"    {k}: {v}")
                    print()

            elif cmd == "5" or cmd == "dialogue":
                dream_id = _select_dream(client, "Open dialogue")
                if not dream_id:
                    continue
                d = client.get_dream(dream_id)
                print(f"\n  💬 Dialogue with: {d.title or d.id}")
                print("  (type 'exit' to end, 'complete' to finish dialogue)\n")
                while True:
                    msg = input("  You: ").strip()
                    if msg.lower() in ("exit", "quit"):
                        break
                    if msg.lower() == "complete":
                        grounded = client.complete_dialogue(dream_id)
                        print(f"  ✅ Dialogue grounded at {grounded}")
                        break
                    if not msg:
                        continue
                    print("  Facilitator: ", end="", flush=True)
                    events = client.dialogue_turn(dream_id, msg)
                    for ev in events:
                        if ev.get("type") == "token":
                            print(ev.get("value", ""), end="", flush=True)
                        elif ev.get("type") == "done":
                            print()
                            print(f"  (turns: {ev.get('turnsUsed')}/{ev.get('turnsRemaining', 0) + ev.get('turnsUsed', 0)})")
                    print()

            elif cmd == "6" or cmd == "analyze":
                dream_id = _select_dream(client, "Analyze dream")
                if not dream_id:
                    continue
                print("\n  🔮 Analyzing dream...\n")
                analysis = client.analyze_dream(dream_id)
                print(f"\n  ✅ Analysis complete!\n")
                for k, v in analysis.items():
                    if isinstance(v, str):
                        print(f"  {k}: {v[:200]}")
                    elif isinstance(v, list):
                        print(f"  {k}: {v}")
                print()

            elif cmd == "7" or cmd == "delete":
                dream_id = _select_dream(client, "Delete dream")
                if not dream_id:
                    continue
                confirm = input(f"  Are you sure? [y/N]: ").strip().lower()
                if confirm == "y":
                    client.delete_dream(dream_id)
                    print("  ✅ Dream deleted.")

            elif cmd == "8" or cmd == "backup":
                result = client.full_backup_workflow()

            elif cmd == "9" or cmd == "restore":
                client.full_restore_workflow()

            elif cmd == "h" or cmd == "health":
                h = client.health()
                print(f"  🟢 API Status: {h.get('status')} (v{h.get('version')})")

            elif cmd == "q" or cmd == "quit":
                print("\n  🌙 Sweet dreams.\n")
                break

            else:
                print("  ❓ Unknown option. Try again.")

        except AuthenticationError as e:
            print(f"\n  🔒 {e}")
        except PaymentRequiredError as e:
            print(f"\n  💳 {e}")
        except RateLimitError as e:
            print(f"\n  ⏳ {e}")
        except OneirosError as e:
            print(f"\n  ❌ {e}")
        except KeyboardInterrupt:
            print("\n\n  👋 Goodbye.\n")
            break

        print()

    client.close()


# ══════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════


def main():
    """Entry point. Runs interactive CLI by default.

    Pass --script to run a quick non-interactive demo.
    """
    if "--script" in sys.argv:
        _run_script_mode()
    else:
        _run_interactive()


def _run_script_mode():
    """Non-interactive demo/test mode."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with OneirosClient(persist=False) as client:
        # 1. Register
        cid = client.register()
        print(f"✅ Registered: {cid}")

        # 2. Record a dream
        dream = client.create_dream(
            "I was walking through an ancient library. The books were alive, "
            "whispering secrets in forgotten languages. A shadowy figure "
            "pointed to a glowing tome on the highest shelf.",
            title="The Living Library",
        )
        print(f"✅ Dream recorded: {dream.id}")

        # 3. List dreams
        dreams = client.list_dreams()
        print(f"📚 {len(dreams)} dream(s)")

        # 4. Backup (recovery phase)
        print("\n🔄 Creating backup...")
        phrase = client.create_backup()
        print(f"🔐 Recovery phrase: {' '.join(phrase)}")

        # 5. Restore from backup
        print("\n🔄 Restoring from backup...")
        restored = client.restore_from_backup(phrase)
        print(f"✅ Restored {len(restored)} dream(s)")

        print("\n✅ All operations completed successfully!")


if __name__ == "__main__":
    main()
