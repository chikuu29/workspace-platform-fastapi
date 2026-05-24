from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.common.responses import bad_request, not_found
from app.modules.hostel.entities.guest import full_name
from app.modules.hostel.entities.room import occupants
from app.modules.hostel.services.base_service import BaseHostelService, service_logger


class HostelBillingService(BaseHostelService):
    async def generate_invoice(self, data: Dict[str, Any]) -> Dict[str, Any]:
        guest_id = data.get("guest_id") 
        if not guest_id:
            bad_request(message="guest_id is required.")

        guest_doc = await self.repositories.guests.find_by_guest_id(guest_id)
        if not guest_doc:
            not_found(message=f"Guest '{guest_id}' not found.")

        room_number = guest_doc["data"].get("room_number")
        if not room_number:
            bad_request(message=f"Guest '{guest_id}' is not currently allocated to any room.")

        room_doc = await self.repositories.rooms.find_by_number(room_number)
        if not room_doc:
            not_found(message=f"Allocated Room '{room_number}' not found.")

        base_rent = float(room_doc["data"].get("rentAmount") or 5000.0)
        utility_split_charge = 0.0
        utility_notes = ""
        if data.get("is_utility_split") and data.get("utility_total_amount"):
            roommates_count = len(occupants(room_doc["data"]))
            total_bill = float(data["utility_total_amount"])
            if roommates_count > 0:
                utility_split_charge = round(total_bill / roommates_count, 2)
                utility_notes = (
                    f"Split billing for {data.get('utility_type', 'Utilities')}: "
                    f"Total Room Bill {total_bill} divided by {roommates_count} "
                    f"roommates = {utility_split_charge} each."
                )
            else:
                utility_split_charge = total_bill
                utility_notes = "Room is occupied solely by this guest. Full utility charge applied."

        invoice_id = await self.sequence.simple("invoice", prefix="INV")
        guest_name = full_name(guest_doc["data"])
        invoice_data = {
            "invoice_id": invoice_id,
            "guest_id": guest_id,
           
            "guest_name": guest_name,
            "tenant_name": guest_name,
            "room_number": room_number,
            "base_rent": base_rent,
            "utility_charge": utility_split_charge,
            "utility_notes": utility_notes,
            "amount_due": base_rent + utility_split_charge,
            "amount_paid": 0.0,
            "status": "Unpaid",
            "description": data.get("description", "Monthly Rent Invoice"),
            "billing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        service_logger.info(
            "Generated invoice org=%s user=%s invoice_id=%s guest_id=%s",
            self.ctx.org_id,
            self.ctx.user_id,
            invoice_id,
            guest_id,
        )
        return await self.repositories.invoices.create(invoice_data)

    async def record_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        invoice_id = data.get("invoice_id")
        payment_amount = float(data.get("amount", 0.0))

        if not invoice_id:
            bad_request(message="invoice_id is required.")
        if payment_amount <= 0.0:
            bad_request(message="Payment amount must be greater than zero.")

        invoice_doc = await self.repositories.invoices.find_by_invoice_id(invoice_id)
        if not invoice_doc:
            not_found(message=f"Invoice '{invoice_id}' not found.")

        current_due = float(invoice_doc["data"].get("amount_due") or 0.0)
        current_paid = float(invoice_doc["data"].get("amount_paid") or 0.0)
        if current_due <= 0.0:
            bad_request(message="This invoice has already been fully paid.")

        new_paid = current_paid + payment_amount
        new_due = max(0.0, current_due - payment_amount)
        service_logger.info(
            "Recording payment org=%s user=%s invoice_id=%s amount=%s",
            self.ctx.org_id,
            self.ctx.user_id,
            invoice_id,
            payment_amount,
        )
        updated = await self.repositories.invoices.update_by_invoice_id(
            invoice_id,
            {
                "amount_due": new_due,
                "amount_paid": new_paid,
                "status": "Paid" if new_due == 0.0 else "Partially Paid",
                "payment_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "payment_method": data.get("payment_method", "Cash"),
            },
        )
        if not updated:
            not_found(message=f"Invoice '{invoice_id}' not found.")
        return updated

    async def list_billing(self, skip: int, limit: int) -> Dict[str, Any]:
        documents = await self.repositories.invoices.list(
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        return {"documents": documents, "total": await self.repositories.invoices.total()}

