import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def calculate_salary_breakdown(gross_pay, config, pf_percent=12.0, esi_percent=0.75, gratuity_percent=4.81, gratuity_threshold_years=5):
    """
    Calculates the bifurcation of gross salary into components and statutory deductions.
    config can contain:
    - basic_salary, hra, conveyance, special_allowance (overrides)
    - pf_enabled, esi_enabled, gratuity_enabled, professional_tax (flags/amounts)
    - tenure_years (for gratuity eligibility)
    """
    
    # ... (Same as before)
    basic = config.get('basic_salary')
    if basic is None or basic == 0:
        basic = round(gross_pay * 0.5, 2)
        
    hra = config.get('hra')
    if hra is None or hra == 0:
        hra = round(gross_pay * 0.2, 2)
        
    conv = config.get('conveyance')
    if conv is None or conv == 0:
        conv = 0 # Default to 0 if not explicitly set
        
    spec = config.get('special_allowance')
    if spec is None or spec == 0:
        spec = max(0, gross_pay - (basic + hra + conv))
    
    # Recalculate gross based on components if they were fixed
    gross_calc = basic + hra + conv + spec
    
    # 2. Statutory Deductions (Employee contribution)
    pf_employee = 0
    if config.get('pf_enabled'):
        # Dynamic % of Basic, capped at 15,000 basic limit
        pf_basis = min(basic, 15000)
        pf_employee = round(pf_basis * (pf_percent / 100.0), 2)
        
    esi_employee = 0
    if config.get('esi_enabled') and gross_calc <= 21000:
        # Dynamic % of Gross
        esi_employee = round(gross_calc * (esi_percent / 100.0), 2)
        
    pt = config.get('professional_tax') or 0
    
    # 3. Provisions (Employer contribution/cost factors)
    gratuity_cost = 0
    if config.get('gratuity_enabled'):
        tenure = config.get('tenure_years', 0)
        # Apply threshold if provided
        if tenure >= gratuity_threshold_years:
            # Typically 4.81% of Basic
            gratuity_cost = round(basic * (gratuity_percent / 100.0), 2)
        
    total_statutory = pf_employee + esi_employee + pt
    net_before_advances = gross_calc - total_statutory
    
    return {
        "components": {
            "basic": basic,
            "hra": hra,
            "conveyance": conv,
            "special_allowance": spec
        },
        "deductions": {
            "pf": pf_employee,
            "esi": esi_employee,
            "pt": pt,
            "total_statutory": total_statutory
        },
        "provisions": {
            "gratuity": gratuity_cost
        },
        "gross": gross_calc,
        "net_before_advances": net_before_advances
    }

def get_pending_advances(conn, person_id, month_str):
    """
    Fetch pending advances for a person likely to be deducted.
    month_str: YYYY-MM
    """
    c = conn.cursor()
    # Support both PG and SQLite
    is_pg = getattr(conn, "_is_pg", False)
    if is_pg:
        c.execute("SELECT id, amount FROM advances WHERE person_id = %s AND deduction_month = %s AND status = 'pending'", (person_id, month_str))
    else:
        c.execute("SELECT id, amount FROM advances WHERE person_id = ? AND deduction_month = ? AND status = 'pending'", (person_id, month_str))
    return c.fetchall()

def mark_advances_deducted(conn, advance_ids):
    if not advance_ids:
        return
    c = conn.cursor()
    is_pg = getattr(conn, "_is_pg", False)
    if is_pg:
        # Convert to tuple for IN clause
        if len(advance_ids) == 1:
            c.execute("UPDATE advances SET status = 'deducted' WHERE id = %s", (advance_ids[0],))
        else:
            c.execute("UPDATE advances SET status = 'deducted' WHERE id IN %s", (tuple(advance_ids),))
    else:
        placeholders = ', '.join(['?'] * len(advance_ids))
        c.execute(f"UPDATE advances SET status = 'deducted' WHERE id IN ({placeholders})", advance_ids)
    conn.commit()
