"""Smoke test for all 13 templates — renders each with realistic sample
answers and reports pass/fail per template without stopping on the first
failure, so one broken template doesn't hide the status of the other 11.
This is NOT the same depth of adversarial testing the first two templates
got (the scope-leak bug, the XML-escape bug) — it verifies each template
renders successfully end-to-end and does a basic sanity check on the
output, not a full bug hunt per template."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.drafting import DraftSession, render_document, ALL_TEMPLATE_SPECS

# Realistic sample answers per field name — reused across specs wherever a
# field name matches, so this stays compact instead of 12 full answer sets.
SAMPLE_VALUES = {
    "work_order_no": "QCI/WO/2026/030", "work_order_date": "19 August 2026",
    "amc_no": "QCI/AMC/2026/004", "amc_date": "19 August 2026",
    "mou_no": "QCI/MOU/2026/011", "mou_date": "19 August 2026",
    "agreement_no": "QCI/AGR/2026/009", "agreement_date": "19 August 2026",
    "proposal_no": "QCI/PROP/2026/015", "proposal_date": "19 August 2026",
    "issuing_organisation": "Quality Council of India",
    "contractor_name": "Bharat Digital Systems Pvt. Ltd.", "contractor_address": "Noida, UP",
    "project_title": "Annual IT Infrastructure Support",
    "scope_of_work_brief": "provision of IT helpdesk, network monitoring, and server maintenance for QCI's Delhi office",
    "contract_value": "Rs. 15,00,000", "start_date": "1 September 2026", "completion_period": "12 months",
    "payment_terms": "Quarterly in advance",
    "authorized_signatory_name": "R. Sharma", "authorized_signatory_designation": "Director, IT",
    "supplier_name": "Nexora Electronics Pvt. Ltd.", "supplier_address": "Gurgaon, Haryana",
    "item_description_brief": "supply of 50 desktop computers and 10 network switches for office IT upgrade",
    "quantity_and_value": "50 units desktop, 10 units switch; Rs. 22,00,000 total",
    "delivery_date": "15 September 2026", "delivery_location": "QCI HQ, New Delhi",
    "warranty_terms": "3 years onsite warranty on all hardware",
    "vendor_name": "TechCare Services Pvt. Ltd.", "vendor_address": "Noida, UP",
    "equipment_covered_brief": "maintenance of HVAC systems, UPS units, and fire safety equipment across QCI's office premises",
    "amc_period": "1 year from go-live", "service_frequency": "Quarterly preventive maintenance",
    "response_time_sla": "4 hours for critical breakdowns",
    "amc_value": "Rs. 8,00,000 per annum",
    "party_a_name": "Quality Council of India", "party_b_name": "National Productivity Council",
    "party_b_address": "Lodhi Road, New Delhi", "mou_title": "Collaboration on Quality Benchmarking",
    "background_brief": "both organisations share an interest in improving quality benchmarks across Indian industry sectors",
    "objectives_brief": "jointly conduct quality audits, publish benchmarking reports, and organise capacity-building workshops",
    "duration": "3 years from date of signing",
    "signatory_a_name": "Anjali Verma", "signatory_a_designation": "CEO, QCI",
    "signatory_b_name": "Vikram Singh", "signatory_b_designation": "Director General, NPC",
    "indian_party_name": "Quality Council of India", "foreign_party_name": "Singapore Accreditation Council",
    "foreign_party_country": "Singapore",
    "purpose_brief": "establish mutual recognition of accreditation outcomes between the two councils",
    "areas_of_cooperation_brief": "joint assessor training, information exchange on accreditation standards, and periodic review meetings",
    "signatory_indian_name": "Anjali Verma", "signatory_indian_designation": "CEO, QCI",
    "signatory_foreign_name": "Wei Tan", "signatory_foreign_designation": "Director, SAC",
    "department_a_name": "Quality Council of India", "department_b_name": "Ministry of MSME",
    "subject_matter_brief": "coordinated support for quality certification of MSME clusters across India",
    "responsibilities_brief": "QCI will conduct assessments and MSME Ministry will facilitate outreach to eligible clusters",
    "review_period": "Annually",
    "signatory_b_name_interdept": "unused",
    "client_name": "Quality Council of India",
    "provider_name": "SecureNet Facilities Pvt. Ltd.", "provider_address": "Gurgaon, Haryana",
    "service_description_brief": "provision of security personnel and access control systems for QCI's office premises",
    "sla_terms_brief": "24x7 security coverage with incident response within 15 minutes",
    "contract_duration": "2 years",
    "termination_notice_period": "60 days written notice",
    "signatory_provider_name": "Manoj Gupta", "signatory_provider_designation": "Operations Head, SecureNet",
    "signatory_client_name": "R. Sharma", "signatory_client_designation": "Director, IT",
    "consultant_name": "Dr. Kavita Rao", "consultant_address": "Bengaluru, Karnataka",
    "consultancy_scope_brief": "advisory support on digital transformation strategy for QCI's accreditation boards",
    "deliverables_brief": "a digital roadmap document, quarterly progress reviews, and a final recommendations report",
    "fee_structure": "Rs. 5,00,000 per quarter", "engagement_period": "6 months",
    "signatory_consultant_name": "Dr. Kavita Rao", "signatory_consultant_designation": "Principal Consultant",
    "licensor_name": "Quality Council of India", "licensee_name": "EduTech Solutions Pvt. Ltd.",
    "licensee_address": "Pune, Maharashtra",
    "ip_description_brief": "QCI's training curriculum and certification materials for quality management courses",
    "usage_terms_brief": "non-exclusive use limited to online course delivery, no resale or sublicensing permitted",
    "royalty_terms": "10% of course revenue, paid quarterly", "license_duration": "2 years, renewable",
    "signatory_licensor_name": "Anjali Verma", "signatory_licensor_designation": "CEO, QCI",
    "signatory_licensee_name": "Rohan Mehta", "signatory_licensee_designation": "CEO, EduTech Solutions",
    "submitted_by": "Innotech Consulting Pvt. Ltd.", "submitted_to": "Quality Council of India",
    "technical_approach_brief": "a phased implementation using agile methodology with monthly stakeholder reviews",
    "team_composition_brief": "a 6-member team including a project lead, 2 senior consultants, and 3 analysts",
    "implementation_timeline": "6 months across 3 phases",
    "signatory_name": "Suresh Iyer", "signatory_designation": "Managing Partner, Innotech Consulting",
    "cost_breakdown_brief": "cost split across personnel (60%), infrastructure (25%), and contingency (15%)",
    "payment_schedule_brief": "30% advance, 40% on midterm milestone, 30% on completion",
    "total_value": "Rs. 45,00,000", "validity_period": "120 days",
    "executive_summary_brief": "a comprehensive digital upgrade proposal combining infrastructure modernisation with staff training",
    "approach_and_cost_brief": "phased rollout over 6 months with costs allocated proportionally to each phase's scope",
    "understanding_brief": "the client needs a modern, scalable citizen-facing portal that integrates with existing government identity systems",
    "compliance_summary_brief": "our solution addresses every requirement in the tender scope of work through a phased delivery plan",
    "information_architecture_brief": "a three-tier sitemap covering citizen services, training provider onboarding, and administrative reporting",
    "architecture_intro_brief": "the solution follows a modern layered architecture deployed on AWS",
    "architecture_layers": "Frontend: React SPA served via CloudFront CDN\nSecurity: WAF, OAuth2, rate limiting\nBackend: Node.js REST API on ECS\nData: PostgreSQL on Amazon RDS with daily backups",
    "data_flow_intro_brief": "the enquiry submission flow validates and stores every citizen request before any notification is attempted",
    "data_flow_steps": "Citizen submits form\nValidate input and check for spam\nPersist to database\nQueue notification",
    "methodology_brief": "a five-phase delivery approach covering discovery, design, build, testing, and handover with formal gates",
    "about_company": "",
}


def build_session(fields):
    session = DraftSession(fields=fields)
    for name, _question, _default in fields:
        value = SAMPLE_VALUES.get(name)
        if value is None:
            raise KeyError(f"No sample value defined for field {name!r}")
        accepted, error = session.answer(name, value)
        if not accepted:
            raise AssertionError(f"Sample value for {name!r} rejected: {error}")
    return session


def main():
    results = []
    for spec in ALL_TEMPLATE_SPECS:
        print(f"\n--- {spec.key} ---")
        try:
            session = build_session(spec.fields)
            path = render_document(session, spec)
            size = path.stat().st_size
            print(f"OK: {path.name} ({size} bytes)")
            results.append((spec.key, True, str(path)))
        except Exception as e:
            print(f"FAIL: {type(e).__name__}: {e}")
            results.append((spec.key, False, str(e)))

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)} templates rendered successfully")
    for key, ok, detail in results:
        print(f"  {'OK  ' if ok else 'FAIL'} {key}" + ("" if ok else f" — {detail}"))


if __name__ == "__main__":
    main()
