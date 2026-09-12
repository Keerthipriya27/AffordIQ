"""
Conflict resolution module implementing the strict hierarchy:
Verified Document (Image) > Direct User Message > Base Scheduled Event.
Also resolves blank event amounts from linked images and de-duplicates events.
"""
from decimal import Decimal
from typing import List, Dict, Any, Optional
from pathlib import Path

from code.models import Event, Message, ImageRecord, EvidenceRecord
from code.evidence_extractor import EvidenceExtractor
from code.config import setup_logging

logger = setup_logging(__name__)

class ConflictResolver:
    def __init__(self, evidence_extractor: EvidenceExtractor):
        self.extractor = evidence_extractor

    def resolve_events(
        self,
        events: List[Event],
        messages: List[Message],
        images: List[ImageRecord],
        media_dir: Path
    ) -> List[Event]:
        """
        Resolves conflicts across events, messages, and images for a user.
        Applies hierarchy: Verified Document (Image) > Direct User Message > Base Scheduled Event.
        """
        # Map images by image_id and by related_event_id
        img_by_id: Dict[str, ImageRecord] = {img.image_id: img for img in images}
        img_by_related_event: Dict[str, ImageRecord] = {
            img.related_event_id: img for img in images if img.related_event_id
        }

        resolved_events: List[Event] = []
        seen_event_ids = set()

        for ev in events:
            # Event IDs identify records.  Category/amount/date signatures are
            # not safe keys: two subscriptions can legitimately be identical.
            if ev.event_id in seen_event_ids:
                logger.info(f"Deduplicating repeated event id: {ev.event_id}")
                continue
            seen_event_ids.add(ev.event_id)

            # 2. Blank Event Amount Resolution (NEVER default to 0.00)
            linked_img = None
            if ev.image_id and ev.image_id in img_by_id:
                linked_img = img_by_id[ev.image_id]
            elif ev.event_id in img_by_related_event:
                linked_img = img_by_related_event[ev.event_id]

            if ev.amount is None or ev.amount <= Decimal("0.00"):
                if linked_img:
                    ext: EvidenceRecord = self.extractor.extract_image_evidence(linked_img, media_dir)
                    if ext.amounts:
                        resolved_amt = ext.amounts[0]
                        logger.info(
                            f"[RESOLVED BLANK AMOUNT] Event {ev.event_id} ({ev.category}) "
                            f"blank amount resolved to {resolved_amt} {ext.currencies[0] if ext.currencies else ev.currency} "
                            f"from verified Image {linked_img.image_id} (confidence: {ext.confidence})"
                        )
                        ev.amount = resolved_amt
                        if ext.currencies:
                            ev.currency = ext.currencies[0]
                    else:
                        logger.error(f"Event {ev.event_id} has blank amount and linked Image {linked_img.image_id} yielded no amount!")
                else:
                    logger.error(f"Event {ev.event_id} has BLANK amount and NO linked image found! (NEVER defaulting to 0)")

            # 3. Message Direct Evidence Override (Direct Message > Base Scheduled Event)
            cancelled = False
            for msg in messages:
                msg_ext: EvidenceRecord = self.extractor.extract_message_evidence(msg)
                
                # Check if message targets this event
                is_match = False
                if msg.related_event_id and msg.related_event_id == ev.event_id:
                    is_match = True
                else:
                    # Check updates in message
                    for upd in msg_ext.event_updates:
                        if upd.get("action") not in {"CANCEL", "UPDATE_AMOUNT", "CONFIRM", "REFUND"}:
                            continue
                        if upd.get("related_event_id") == ev.event_id:
                            is_match = True
                            break
                        if upd.get("target_category") and upd["target_category"].lower() in ev.category.lower():
                            is_match = True
                            break

                if is_match and not cancelled:
                    # A cancellation without an explicit relation/category is
                    # not allowed to negate unrelated events.
                    explicit_cancel = (
                        (msg.related_event_id == ev.event_id)
                        or any(
                            upd.get("action") == "CANCEL"
                            and (upd.get("related_event_id") == ev.event_id
                                 or (upd.get("target_category") or "").lower() == ev.category.lower())
                            for upd in msg_ext.event_updates
                        )
                    )
                    if (msg_ext.cancellation or msg_ext.status == "cancelled") and explicit_cancel:
                        logger.info(
                            f"[CONFLICT RESOLVED: Message > Event] Event {ev.event_id} ({ev.category}) "
                            f"marked CANCELLED per message {msg.message_id}"
                        )
                        ev.status = "cancelled"
                        cancelled = True
                    elif msg_ext.amounts and any(
                        upd.get("action") == "UPDATE_AMOUNT"
                        and (upd.get("related_event_id") == ev.event_id
                             or (upd.get("target_category") or "").lower() == ev.category.lower()
                             or (msg.related_event_id == ev.event_id))
                        for upd in msg_ext.event_updates
                    ):
                        new_amt = msg_ext.amounts[0]
                        logger.info(
                            f"[CONFLICT RESOLVED: Message > Event] Event {ev.event_id} ({ev.category}) "
                            f"amount updated {ev.amount} -> {new_amt} per message {msg.message_id}"
                        )
                        try:
                            ev.amount = Decimal(str(new_amt))
                        except Exception:
                            logger.warning("Ignoring malformed evidence amount for event %s", ev.event_id)
                            continue
                        if msg_ext.currencies:
                            ev.currency = msg_ext.currencies[0]

            # 4. Verified Document Priority Override (Verified Document > Direct Message > Event)
            # If an image exists, its verified facts supersede base events or general claims
            if linked_img and ev.amount is not None and not cancelled:
                img_ext: EvidenceRecord = self.extractor.extract_image_evidence(linked_img, media_dir)
                if img_ext.amounts:
                    doc_amt = img_ext.amounts[0]
                    if doc_amt != ev.amount:
                        logger.info(
                            f"[CONFLICT RESOLVED: Document > Message/Event] Event {ev.event_id} ({ev.category}) "
                            f"amount overridden {ev.amount} -> {doc_amt} from verified Image {linked_img.image_id}"
                        )
                        ev.amount = doc_amt
                    if img_ext.status and img_ext.status != ev.status:
                        ev.status = img_ext.status

            resolved_events.append(ev)

        return resolved_events
