import pytest
from app.modules.billing.engines.tax_engine import (
    compute_line_tax,
    compute_invoice_tax,
    extract_state_code,
)
from app.modules.billing.engines.pricing_engine import (
    compute_line_pricing,
    compute_invoice_totals,
)


def test_state_code_extraction():
    assert extract_state_code("29AABCU9603R1ZM") == "29"
    assert extract_state_code("27AADCB2230M1Z3") == "27"
    assert extract_state_code("XX") == ""
    assert extract_state_code(None) == ""


def test_tax_engine_intra_state():
    # 29 is Karnataka, seller and supply are both 29 (intra-state)
    result = compute_line_tax(
        taxable_amount=10000.0,
        tax_category="higher",  # standard standard is 18% standard, higher is 18%, etc.
        seller_gstin="29AABCU9603R1ZM",
        place_of_supply="29",
    )
    assert result.is_inter_state is False
    assert result.tax_rate == 18.0
    assert result.total_tax == 1800.0
    assert result.cgst_amount == 900.0
    assert result.sgst_amount == 900.0
    assert result.igst_amount == 0.0


def test_tax_engine_inter_state():
    # 29 (Karnataka) to 27 (Maharashtra) (inter-state)
    result = compute_line_tax(
        taxable_amount=10000.0,
        tax_category="higher",
        seller_gstin="29AABCU9603R1ZM",
        place_of_supply="27",
    )
    assert result.is_inter_state is True
    assert result.tax_rate == 18.0
    assert result.total_tax == 1800.0
    assert result.cgst_amount == 0.0
    assert result.sgst_amount == 0.0
    assert result.igst_amount == 1800.0


def test_pricing_engine():
    # Quantity 2, unit price 5000, 10% percentage discount
    line = compute_line_pricing(
        quantity=2.0,
        unit_price=5000.0,
        discount_type="percentage",
        discount_value=10.0,
        tax_amount=900.0,
    )
    assert line.gross_amount == 10000.0
    assert line.discount_amount == 1000.0
    assert line.taxable_amount == 9000.0
    assert line.line_total == 9900.0
