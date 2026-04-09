"""
RBI Compliance Database Seed Script
=====================================
Inserts realistic, research-backed compliance rules into:
  - MongoDB  (rules, circulars, relationships, topics collections)
  - Qdrant   (vector embeddings for each rule + topic)

Data is sourced from:
  - RBI Master Direction – KYC (2016, updated 2023)
  - RBI Basel III Capital Adequacy Circular (2023-24)
  - RBI NBFC Scale-Based Regulation Directions 2023
  - RBI NPA / IRACP Master Circular 2023
  - RBI Payment Aggregators Directions 2025
  - RBI FEMA / LRS Guidelines
  - RBI Governance Guidelines for Banks

Run:
    pip install pymongo qdrant-client sentence-transformers
    python seed_data.py
"""

import uuid, hashlib, sys
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
MONGO_URI        = "mongodb://localhost:27017"
MONGO_DB         = "dummy_db"
QDRANT_PATH      = "./qdrant_storage"
COLLECTION_NAME  = "compliance_rules"
EMBED_MODEL      = "all-MiniLM-L6-v2"
EMBED_DIM        = 384

TOPIC_COLORS = {
    "commercial_banks":"#378ADD","NBFC":"#7F77DD","payment_banks":"#1D9E75",
    "small_financial_banks":"#639922","Regional_Rural_Bank":"#BA7517",
    "local_area_banks":"#BA7517","Urban_Cooperative_Bank":"#D85A30",
    "Rural_Cooperative_Bank":"#D85A30","All_India_Financial_Institutions":"#D4537E",
    "Asset_Reconstruction_Companies":"#E24B4A","Credit_Information_Services":"#888780",
    "KYC":"#1D9E75","AML":"#D85A30","PMLA":"#993556","forex":"#7F77DD",
    "governance":"#888780","general":"#888780","payment_banks":"#1D9E75",
}

NOW = datetime.utcnow().isoformat()

# ─────────────────────────────────────────────────────────────
# SEED DATA
# Every entry: (rule_id, title, topic, subtopic, source_circular_id,
#               effective_date, conditions, requirements, exceptions,
#               penalties, plain_language_summary, tags, related_rule_ids)
# ─────────────────────────────────────────────────────────────

RULES = [

    # ══════════════════════════════════════════════════════════
    # KYC — small_account
    # ══════════════════════════════════════════════════════════
    ("KYC_SA_001","Small Account Balance Limit","KYC","small_account","RBI_KYC_2023_45","2023-10-17",
     [{"field":"account_type","operator":"equals","value":"small_account"}],
     [{"type":"limit","field":"max_balance","value":100000,"currency":"INR","description":"Maximum balance at any point in a small account shall not exceed ₹1,00,000"}],
     [{"condition":"Account upgraded to full KYC","outcome":"Balance limit removed"}],
     [{"violation":"Balance exceeds ₹1,00,000","action":"Account to be frozen immediately","reference":"Para 3.1 KYC MD 2016"}],
     "A small account opened with self-declaration as KYC can hold a maximum balance of ₹1,00,000 at any point. If the balance exceeds this limit, the account must be frozen until the customer completes full KYC.",
     ["KYC","small_account","balance_limit","simplified_KYC"],["KYC_SA_002","KYC_SA_003"]),

    ("KYC_SA_002","Small Account Annual Credit Limit","KYC","small_account","RBI_KYC_2023_45","2023-10-17",
     [{"field":"account_type","operator":"equals","value":"small_account"}],
     [{"type":"limit","field":"annual_credits","value":200000,"currency":"INR","description":"Total credits in a financial year shall not exceed ₹2,00,000"}],
     [{"condition":"Credits are from government schemes or wages","outcome":"May be exempted from aggregate limit"}],
     [],
     "The total amount credited to a small account in any financial year must not exceed ₹2,00,000. This limit covers all inward transfers, cash deposits, and other credits combined.",
     ["KYC","small_account","annual_credit_limit"],["KYC_SA_001"]),

    ("KYC_SA_003","Small Account Monthly Withdrawal Limit","KYC","small_account","RBI_KYC_2023_45","2023-10-17",
     [{"field":"account_type","operator":"equals","value":"small_account"}],
     [{"type":"limit","field":"monthly_withdrawal","value":10000,"currency":"INR","description":"Monthly withdrawals and transfers shall not exceed ₹10,000"}],
     [],
     [{"violation":"Monthly withdrawal exceeds ₹10,000","action":"Transaction to be declined","reference":"Para 3.1(iii) KYC MD 2016"}],
     "A small account holder cannot withdraw or transfer more than ₹10,000 in a single month. This applies to all debits including ATM withdrawals, NEFT/RTGS transfers, and point-of-sale transactions.",
     ["KYC","small_account","withdrawal_limit"],["KYC_SA_001"]),

    ("KYC_SA_004","Small Account Foreign Remittance Restriction","KYC","small_account","RBI_KYC_2023_45","2023-10-17",
     [{"field":"account_type","operator":"equals","value":"small_account"}],
     [],
     [],
     [{"violation":"Inward foreign remittance credited to small account","action":"Remittance to be returned to sender","reference":"Para 3.1(iv) KYC MD 2016"}],
     "Small accounts are not permitted to receive inward foreign remittances. Any such credit must be reversed and the funds returned to the originating party. The customer must upgrade to full KYC to receive foreign remittances.",
     ["KYC","small_account","foreign_remittance","FEMA"],["KYC_SA_001","KYC_RK_001"]),

    ("KYC_SA_005","Small Account 12-Month Conversion Requirement","KYC","small_account","RBI_KYC_2023_45","2023-10-17",
     [{"field":"account_type","operator":"equals","value":"small_account"},{"field":"account_age_months","operator":"greater_than","value":12}],
     [],
     [{"condition":"Customer has applied for full KYC and process is underway","outcome":"Account may continue for additional 12 months"}],
     [{"violation":"Small account operated beyond 12 months without full KYC","action":"Account to be frozen","reference":"Para 3.1(v) KYC MD 2016"}],
     "A small account can only be operated for 12 months from opening. After 12 months, the account must be frozen unless the customer submits full KYC documents. An additional 12-month extension is allowed only if KYC documents have been applied for.",
     ["KYC","small_account","account_validity","time_limit"],["KYC_SA_001","KYC_CID_001"]),

    # ══════════════════════════════════════════════════════════
    # KYC — re_kyc
    # ══════════════════════════════════════════════════════════
    ("KYC_RK_001","Periodic KYC Updation — Low Risk","KYC","re_kyc","RBI_KYC_2023_45","2023-10-17",
     [{"field":"customer_risk_category","operator":"equals","value":"low"}],
     [{"type":"procedure","field":"re_kyc_periodicity","value":10,"description":"Re-KYC every 10 years for low-risk customers"}],
     [],
     [{"violation":"Re-KYC not completed within stipulated period","action":"Account to be restricted to essential services only","reference":"Para 38 KYC MD 2016"}],
     "Low-risk customers must have their KYC records updated at least once every 10 years. If a customer does not submit re-KYC documents by the due date, the bank should restrict their account to essential services like salary credits and EMI debits.",
     ["KYC","re_kyc","periodic_update","low_risk"],["KYC_RK_002","KYC_RK_003"]),

    ("KYC_RK_002","Periodic KYC Updation — Medium Risk","KYC","re_kyc","RBI_KYC_2023_45","2023-10-17",
     [{"field":"customer_risk_category","operator":"equals","value":"medium"}],
     [{"type":"procedure","field":"re_kyc_periodicity","value":8,"description":"Re-KYC every 8 years for medium-risk customers"}],
     [],
     [],
     "Medium-risk customers require KYC record updates every 8 years. Banks must proactively contact such customers at least 6 months before the re-KYC due date to collect updated documents.",
     ["KYC","re_kyc","periodic_update","medium_risk"],["KYC_RK_001","KYC_RK_003"]),

    ("KYC_RK_003","Periodic KYC Updation — High Risk","KYC","re_kyc","RBI_KYC_2023_45","2023-10-17",
     [{"field":"customer_risk_category","operator":"equals","value":"high"}],
     [{"type":"procedure","field":"re_kyc_periodicity","value":2,"description":"Re-KYC every 2 years for high-risk customers"}],
     [],
     [{"violation":"High-risk customer re-KYC not done in 2 years","action":"Account to be immediately restricted","reference":"Para 38 KYC MD 2016"}],
     "High-risk customers — including Politically Exposed Persons (PEPs), non-residents, and those in high-risk geographies — must have their KYC updated every 2 years. Non-compliance results in immediate account restriction.",
     ["KYC","re_kyc","periodic_update","high_risk","PEP"],["KYC_RK_001","KYC_PEP_001"]),

    ("KYC_RK_004","Re-KYC Trigger on Change of Address","KYC","re_kyc","RBI_KYC_2023_45","2023-10-17",
     [],
     [{"type":"procedure","field":"address_verification","description":"Address proof must be obtained and verified within 6 months of customer-reported address change"}],
     [],
     [],
     "When a customer reports a change of address, the bank must obtain and verify fresh address proof within 6 months. Interim, the bank may update the address on the basis of the customer's self-declaration but must follow up with documentary proof.",
     ["KYC","re_kyc","address_change","document_update"],["KYC_RK_001"]),

    ("KYC_RK_005","Video-Based Re-KYC Permission","KYC","re_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"vcip_channel","description":"Banks may use V-CIP (Video Customer Identification Process) for re-KYC of existing customers"}],
     [],
     [],
     "Banks are permitted to complete re-KYC for existing customers through Video Customer Identification Process (V-CIP) without requiring the customer to visit the branch. The video must be conducted by a trained bank official and recorded for audit purposes.",
     ["KYC","re_kyc","video_kyc","V-CIP","digital"],["KYC_VK_001","KYC_RK_001"]),

    # ══════════════════════════════════════════════════════════
    # KYC — video_kyc
    # ══════════════════════════════════════════════════════════
    ("KYC_VK_001","V-CIP Mandatory Requirements","KYC","video_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"vcip_requirements","description":"Live geolocation, face match with Aadhaar/PAN, official email/mobile OTP verification required"}],
     [],
     [{"violation":"V-CIP conducted without live geolocation capture","action":"KYC deemed incomplete; account not to be opened","reference":"Para 18 KYC MD 2016"}],
     "For Video KYC (V-CIP), the bank must capture the customer's live geolocation, perform a face match with Aadhaar or PAN photo, verify OTP on Aadhaar-linked mobile, and ensure the video is recorded with a timestamp. All these steps are mandatory — missing any one step invalidates the KYC.",
     ["KYC","video_kyc","V-CIP","geolocation","face_match"],["KYC_VK_002","KYC_AK_001"]),

    ("KYC_VK_002","V-CIP Data Storage Requirement","KYC","video_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"video_retention","value":5,"description":"Video recordings of V-CIP sessions must be stored for minimum 5 years"}],
     [],
     [],
     "All video recordings from V-CIP sessions must be securely stored for a minimum of 5 years and must be made available to RBI inspectors on demand. The video must clearly capture the customer's face, the original document, and the bank official's face.",
     ["KYC","video_kyc","V-CIP","data_retention","record_keeping"],["KYC_VK_001"]),

    ("KYC_VK_003","V-CIP Permitted for NBFCs","KYC","video_kyc","RBI_KYC_2023_45","2023-10-17",
     [{"field":"entity_type","operator":"equals","value":"NBFC"}],
     [],
     [],
     [],
     "NBFCs are also permitted to use V-CIP for customer onboarding, subject to the same requirements as banks. The V-CIP must be conducted on the NBFC's own platform and cannot be outsourced to a third-party aggregator unless specifically approved by RBI.",
     ["KYC","video_kyc","V-CIP","NBFC"],["KYC_VK_001","NBFC_FP_001"]),

    ("KYC_VK_004","V-CIP Offline Aadhaar Permitted","KYC","video_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"offline_aadhaar","description":"Offline Aadhaar XML with digitally signed QR code acceptable for V-CIP identification"}],
     [],
     [],
     "During V-CIP, customers may present their offline Aadhaar XML file or the digitally-signed QR code on their Aadhaar card instead of sharing their full Aadhaar number. The bank must verify the XML's digital signature against UIDAI's public key.",
     ["KYC","video_kyc","V-CIP","Aadhaar","offline_Aadhaar"],["KYC_VK_001","KYC_AK_001"]),

    ("KYC_VK_005","V-CIP Consent Requirement","KYC","video_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"customer_consent","description":"Explicit informed consent must be obtained from customer before V-CIP session"}],
     [],
     [],
     "Before starting a V-CIP session, the bank must obtain explicit written or digital consent from the customer confirming that they are aware of the video recording and agree to its use for KYC verification purposes. Consent must be stored along with the video.",
     ["KYC","video_kyc","V-CIP","consent","data_protection"],["KYC_VK_001"]),

    # ══════════════════════════════════════════════════════════
    # KYC — aadhaar_kyc
    # ══════════════════════════════════════════════════════════
    ("KYC_AK_001","Aadhaar e-KYC Authentication Permitted","KYC","aadhaar_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"aadhaar_ekyc","description":"Banks and NBFCs licensed for Aadhaar authentication may use UIDAI e-KYC"}],
     [{"condition":"Entity not licensed for Aadhaar authentication","outcome":"Must use offline Aadhaar XML or other OVDs"}],
     [],
     "Banks and NBFCs that have been granted an Aadhaar authentication license by UIDAI may complete KYC electronically through biometric or OTP-based e-KYC from UIDAI. Entities without this license must use offline Aadhaar or other officially valid documents (OVDs).",
     ["KYC","aadhaar_kyc","e-KYC","UIDAI","biometric"],["KYC_AK_002","KYC_VK_001"]),

    ("KYC_AK_002","Aadhaar-Based KYC for Non-Face-to-Face","KYC","aadhaar_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"non_face_to_face_kyc","description":"Aadhaar OTP-based e-KYC permitted for non-face-to-face customer onboarding"}],
     [],
     [],
     "Aadhaar OTP-based e-KYC is permitted for non-face-to-face onboarding, allowing customers to complete KYC from their mobile or computer without visiting a branch. The Aadhaar number must be verified through a one-time password sent to the Aadhaar-linked mobile number.",
     ["KYC","aadhaar_kyc","e-KYC","non_face_to_face","digital_onboarding"],["KYC_AK_001"]),

    ("KYC_AK_003","Beneficial Ownership Aadhaar Threshold","KYC","aadhaar_kyc","RBI_KYC_2023_45","2023-10-17",
     [{"field":"entity_type","operator":"in","value":"partnership_firm,LLP"}],
     [{"type":"limit","field":"beneficial_ownership_threshold","value":10,"description":"Persons owning 10% or more equity/profit share qualify as Beneficial Owners"}],
     [],
     [],
     "As per October 2023 amendment, the threshold for identifying Beneficial Owners of partnership firms and LLPs has been reduced from 15% to 10%. Any natural person holding 10% or more ownership, profit share, or control rights must be identified and their KYC must be completed.",
     ["KYC","aadhaar_kyc","beneficial_ownership","partnership","PMLA"],["KYC_AK_001","PMLA_BO_001"]),

    ("KYC_AK_004","Aadhaar Masking for Document Storage","KYC","aadhaar_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"aadhaar_masking","description":"First 8 digits of Aadhaar number must be masked when storing physical copies"}],
     [],
     [{"violation":"Storing unmasked Aadhaar copies","action":"Regulatory action under PMLA","reference":"Aadhaar Act 2016 Section 29"}],
     "When storing physical or digital copies of Aadhaar cards, the first 8 digits of the 12-digit Aadhaar number must be masked. Only the last 4 digits may be visible. Banks must upgrade their document management systems to enforce automatic masking.",
     ["KYC","aadhaar_kyc","Aadhaar","data_masking","privacy"],["KYC_AK_001"]),

    ("KYC_AK_005","Central KYC Registry (CKYCR) Upload","KYC","aadhaar_kyc","RBI_KYC_2023_45","2023-04-28",
     [],
     [{"type":"procedure","field":"ckycr_upload","description":"KYC records of all new individual customers must be uploaded to CKYCR within 10 days of account opening"}],
     [],
     [],
     "All regulated entities must upload KYC records of new individual customers to the Central KYC Records Registry (CKYCR) within 10 days of account opening or relationship establishment. This enables other financial institutions to retrieve existing KYC data without re-collecting documents.",
     ["KYC","aadhaar_kyc","CKYCR","record_keeping","digital"],["KYC_AK_001","KYC_CID_001"]),

    # ══════════════════════════════════════════════════════════
    # KYC — customer_identification
    # ══════════════════════════════════════════════════════════
    ("KYC_CID_001","OVD for Individual Customers","KYC","customer_identification","RBI_KYC_2023_45","2023-04-28",
     [{"field":"customer_type","operator":"equals","value":"individual"}],
     [{"type":"procedure","field":"identity_document","description":"Passport, Driving Licence, Voter ID, PAN, Aadhaar, or NREGA Job Card acceptable as OVD for identity"}],
     [],
     [],
     "For individual customers, any one of the following Officially Valid Documents (OVDs) is acceptable for identity verification: Passport, Driving Licence, Voter Identity Card, PAN card, Aadhaar Card, or NREGA Job Card. Banks cannot insist on a specific OVD unless for a specific regulatory purpose.",
     ["KYC","customer_identification","OVD","identity_document"],["KYC_CID_002"]),

    ("KYC_CID_002","PAN Mandatory for High-Value Accounts","KYC","customer_identification","RBI_KYC_2023_45","2023-04-28",
     [{"field":"transaction_amount","operator":"greater_than","value":50000},{"field":"customer_type","operator":"equals","value":"individual"}],
     [{"type":"requirement","field":"PAN_mandatory","description":"PAN or Form 60 mandatory for cash transactions above ₹50,000"}],
     [{"condition":"Customer does not have PAN","outcome":"Form 60 (declaration of no PAN) is acceptable"}],
     [],
     "For any cash transaction of ₹50,000 or more, the customer must provide their PAN card. If the customer does not have a PAN, they must submit Form 60 — a declaration stating the reason for not having a PAN and providing alternative identification.",
     ["KYC","customer_identification","PAN","cash_transaction","Form60"],["KYC_CID_001"]),

    ("KYC_CID_003","Customer Risk Categorisation","KYC","customer_identification","RBI_KYC_2023_45","2023-10-17",
     [],
     [{"type":"procedure","field":"risk_categorisation","description":"All customers must be categorised as Low, Medium, or High risk based on RBI criteria"}],
     [],
     [],
     "Every regulated entity must classify all customers into Low, Medium, or High risk categories based on their background, nature of business, transaction patterns, and geography. This risk rating must be reviewed at least annually and updated whenever there is a significant change in customer activity.",
     ["KYC","customer_identification","risk_categorisation","CDD"],["KYC_CID_004","KYC_RK_001"]),

    ("KYC_CID_004","Enhanced Due Diligence for High-Risk","KYC","customer_identification","RBI_KYC_2023_45","2023-10-17",
     [{"field":"customer_risk_category","operator":"equals","value":"high"}],
     [{"type":"procedure","field":"EDD","description":"Enhanced due diligence mandatory including source of funds verification and senior management approval"}],
     [],
     [],
     "High-risk customers require Enhanced Due Diligence (EDD). This means the bank must verify the source of funds, obtain information about the purpose of the account, and get approval from senior management before opening or continuing a relationship with a high-risk customer.",
     ["KYC","customer_identification","EDD","high_risk","source_of_funds"],["KYC_CID_003","KYC_RK_003"]),

    ("KYC_CID_005","PEP Identification and Enhanced Monitoring","KYC","customer_identification","RBI_KYC_2023_45","2023-10-17",
     [{"field":"customer_type","operator":"equals","value":"PEP"}],
     [{"type":"procedure","field":"PEP_monitoring","description":"PEP accounts require board/senior management approval and enhanced ongoing monitoring"}],
     [],
     [],
     "Politically Exposed Persons (PEPs) — including current and former senior government officials, senior judiciary, military officers, and their close family members — must be identified at account opening. Their accounts require approval from senior management and ongoing enhanced monitoring of all transactions.",
     ["KYC","customer_identification","PEP","enhanced_monitoring","governance"],["KYC_CID_004","KYC_RK_003"]),

    # ══════════════════════════════════════════════════════════
    # AML — suspicious_transactions
    # ══════════════════════════════════════════════════════════
    ("AML_ST_001","STR Filing Obligation","AML","suspicious_transactions","RBI_KYC_2023_45","2023-10-17",
     [],
     [{"type":"procedure","field":"STR_filing","description":"Suspicious Transaction Reports must be filed with FIU-IND within 7 days of forming suspicion"}],
     [],
     [{"violation":"Failure to file STR within 7 days","action":"Penalty under PMLA Section 13","reference":"PMLA Section 12"}],
     "When a bank or NBFC suspects that a transaction involves money laundering, terrorist financing, or other financial crime, it must file a Suspicious Transaction Report (STR) with the Financial Intelligence Unit - India (FIU-IND) within 7 days of forming the suspicion. The suspicion date, not the transaction date, is the trigger.",
     ["AML","STR","FIU_IND","suspicious_transactions","PMLA"],["AML_ST_002","PMLA_RE_001"]),

    ("AML_ST_002","STR Confidentiality — No Tipping Off","AML","suspicious_transactions","RBI_KYC_2023_45","2023-10-17",
     [],
     [],
     [],
     [{"violation":"Informing customer about filed STR","action":"Criminal prosecution under PMLA","reference":"PMLA Section 14"}],
     "After filing a Suspicious Transaction Report, the bank must not inform the customer, directly or indirectly, that an STR has been filed against them. This is known as 'tipping off' and is a criminal offence under PMLA. Even the existence of the STR regime must not be disclosed to the customer.",
     ["AML","STR","tipping_off","confidentiality","PMLA"],["AML_ST_001"]),

    ("AML_ST_003","Wire Transfer STR Threshold","AML","suspicious_transactions","RBI_KYC_2023_45","2023-10-17",
     [{"field":"wire_transfer_amount","operator":"less_than","value":50000}],
     [{"type":"procedure","field":"UTR_required","description":"For wire transfers below ₹50,000 from non-account holders, only UTR number is required"}],
     [],
     [],
     "For wire transfers below ₹50,000 from a non-account-holder customer, the bank only needs to include a Unique Transaction Reference (UTR) number that is traceable back to the originator. Full originator information must be made available to competent authorities within 3 days of a request.",
     ["AML","STR","wire_transfer","UTR","non_account_holder"],["AML_ST_001","AML_CTR_001"]),

    ("AML_ST_004","Principal Officer for STR Reporting","AML","suspicious_transactions","RBI_KYC_2023_45","2023-10-17",
     [],
     [{"type":"procedure","field":"principal_officer","description":"Management-level Principal Officer must be designated for STR reporting to FIU-IND"}],
     [],
     [],
     "Every regulated entity must designate a management-level officer as the Principal Officer responsible for filing STRs and ensuring AML/CFT compliance. The Principal Officer must be of at least middle-management level and their details must be communicated to RBI.",
     ["AML","STR","principal_officer","FIU_IND","governance"],["AML_ST_001","KYC_CID_003"]),

    ("AML_ST_005","Attempted Transaction STR Requirement","AML","suspicious_transactions","RBI_KYC_2023_45","2023-10-17",
     [],
     [{"type":"procedure","field":"attempted_transaction_STR","description":"STR must be filed even for attempted transactions that were declined on suspicion"}],
     [],
     [],
     "Banks must file an STR not only for completed suspicious transactions but also for transactions that were attempted but declined due to suspicion of money laundering or terrorist financing. The STR must clearly state that the transaction was 'attempted but not completed'.",
     ["AML","STR","attempted_transaction","suspicious_transactions"],["AML_ST_001"]),

    # ══════════════════════════════════════════════════════════
    # AML — cash_transactions
    # ══════════════════════════════════════════════════════════
    ("AML_CTR_001","Cash Transaction Report Threshold","AML","cash_transactions","RBI_KYC_2023_45","2023-10-17",
     [{"field":"cash_transaction_amount","operator":"greater_than_equal","value":1000000}],
     [{"type":"procedure","field":"CTR_filing","description":"CTR must be filed with FIU-IND for all cash transactions of ₹10 lakh or above within 15 days of month-end"}],
     [],
     [{"violation":"CTR not filed within 15 days","action":"Penalty under PMLA Section 13","reference":"PMLA Section 12(1)(b)"}],
     "Banks must file a Cash Transaction Report (CTR) with FIU-IND for every cash transaction of ₹10 lakh or more — whether a single transaction or multiple related transactions. CTRs must be filed by the 15th of the month following the transaction month.",
     ["AML","CTR","cash_transaction","FIU_IND","PMLA"],["AML_CTR_002","AML_ST_001"]),

    ("AML_CTR_002","Structured Transactions Aggregation","AML","cash_transactions","RBI_KYC_2023_45","2023-10-17",
     [],
     [],
     [],
     [{"violation":"Allowing structured transactions to avoid ₹10 lakh CTR threshold","action":"Regulatory action and STR filing","reference":"PMLA Section 3"}],
     "Banks must monitor for 'structuring' — where customers split large cash transactions into smaller amounts to avoid the ₹10 lakh CTR reporting threshold. Multiple cash transactions below ₹10 lakh by the same customer within a short period that aggregate above ₹10 lakh must be treated as a single reportable transaction.",
     ["AML","CTR","structuring","cash_transaction","aggregation"],["AML_CTR_001","AML_ST_001"]),

    ("AML_CTR_003","Non-Profit Organisation Cash Monitoring","AML","cash_transactions","RBI_KYC_2023_45","2023-10-17",
     [{"field":"customer_type","operator":"equals","value":"non_profit_organisation"}],
     [{"type":"procedure","field":"NPO_monitoring","description":"Enhanced monitoring of cash transactions of NPOs registered on DARPAN portal"}],
     [],
     [],
     "Non-Profit Organisations (NPOs) must be registered on NITI Aayog's DARPAN portal as a condition for maintaining bank accounts. Banks must conduct enhanced monitoring of all cash transactions of NPOs and file STRs for any unusual patterns.",
     ["AML","cash_transactions","NPO","DARPAN","monitoring"],["AML_CTR_001","KYC_CID_003"]),

    ("AML_CTR_004","Cash Deposit Monitoring at Branch","AML","cash_transactions","RBI_KYC_2023_45","2023-10-17",
     [],
     [{"type":"procedure","field":"cash_deposit_monitoring","description":"Cash deposits above ₹50,000 require PAN/Form 60 and source of funds enquiry"}],
     [],
     [],
     "For cash deposits of ₹50,000 or more, the bank must obtain the customer's PAN card or Form 60, and may enquire about the source of funds. The branch official must be satisfied that the cash has a legitimate source before accepting the deposit.",
     ["AML","cash_transactions","cash_deposit","PAN","source_of_funds"],["AML_CTR_001","KYC_CID_002"]),

    ("AML_CTR_005","ML/TF Risk Assessment Periodicity","AML","cash_transactions","RBI_KYC_2023_45","2023-10-17",
     [],
     [{"type":"procedure","field":"risk_assessment","description":"Board or Board Committee to determine periodicity of ML/TF risk assessment"}],
     [],
     [],
     "The Board of Directors or a Committee of the Board must determine the periodicity of the entity's Money Laundering/Terrorist Financing (ML/TF) risk assessment. The risk assessment must cover all customers, products, services, geographies, and delivery channels.",
     ["AML","cash_transactions","risk_assessment","board","governance"],["AML_ST_004","KYC_CID_003"]),

    # ══════════════════════════════════════════════════════════
    # PMLA — record_keeping
    # ══════════════════════════════════════════════════════════
    ("PMLA_RK_001","Transaction Record Retention Period","PMLA","record_keeping","RBI_PMLA_2023","2023-09-01",
     [],
     [{"type":"procedure","field":"record_retention","value":5,"description":"All transaction records must be maintained for minimum 5 years from transaction date"}],
     [],
     [{"violation":"Records not maintained for 5 years","action":"Penalty under PMLA Section 13","reference":"PMLA Section 12(1)(a)"}],
     "All records of transactions must be maintained for a minimum of 5 years from the date of the transaction. This includes account statements, transaction vouchers, KYC documents, and correspondence related to the transaction. Records must be retrievable within 3 days on demand by authorities.",
     ["PMLA","record_keeping","data_retention","transaction_records"],["PMLA_RK_002","AML_ST_001"]),

    ("PMLA_RK_002","KYC Record Retention After Account Closure","PMLA","record_keeping","RBI_PMLA_2023","2023-09-01",
     [],
     [{"type":"procedure","field":"kyc_record_retention","value":5,"description":"KYC records to be maintained for 5 years after account closure"}],
     [],
     [],
     "Even after an account is closed, all KYC documents and records must be retained for 5 years from the date of closure. This ensures that historical customer information is available for any future investigation or regulatory inquiry.",
     ["PMLA","record_keeping","KYC","account_closure","data_retention"],["PMLA_RK_001","KYC_CID_001"]),

    ("PMLA_RK_003","Group-Level Policy for Record Keeping","PMLA","record_keeping","RBI_PMLA_2023","2023-10-17",
     [{"field":"entity_type","operator":"equals","value":"group_entity"}],
     [{"type":"procedure","field":"group_policy","description":"Group entities must implement group-wide policies for AML record keeping and sharing"}],
     [],
     [],
     "Regulated entities that are part of a group must implement group-wide policies and programs for AML/CFT record keeping. Group companies must be able to share KYC and transaction records within the group for CDD and ML/TF risk management, with appropriate confidentiality safeguards.",
     ["PMLA","record_keeping","group_policy","CDD","confidentiality"],["PMLA_RK_001","PMLA_BO_001"]),

    ("PMLA_RK_004","Cross-Border Correspondent Bank Records","PMLA","record_keeping","RBI_PMLA_2023","2023-09-01",
     [{"field":"relationship_type","operator":"equals","value":"correspondent_banking"}],
     [{"type":"procedure","field":"correspondent_bank_records","description":"Full KYC and ownership structure of correspondent banks must be maintained"}],
     [],
     [],
     "Before establishing correspondent banking relationships, Indian banks must obtain and maintain full KYC records of the foreign correspondent bank, including its ownership structure, regulatory status, AML/CFT controls, and any regulatory actions taken against it.",
     ["PMLA","record_keeping","correspondent_banking","cross_border","CDD"],["PMLA_RK_001","KYC_CID_004"]),

    ("PMLA_RK_005","Confidentiality of PMLA Filings","PMLA","record_keeping","RBI_PMLA_2023","2023-10-17",
     [],
     [],
     [],
     [{"violation":"Disclosure of PMLA filing existence to customer","action":"Criminal prosecution under PMLA Section 14","reference":"PMLA Section 14"}],
     "All records maintained for the purpose of PMLA compliance — including STRs, CTRs, and related investigations — must be kept strictly confidential. No employee, director, or officer may disclose the existence of any PMLA filing to any person, including the customer concerned.",
     ["PMLA","record_keeping","confidentiality","STR","CTR"],["PMLA_RK_001","AML_ST_002"]),

    # ══════════════════════════════════════════════════════════
    # PMLA — beneficial_ownership
    # ══════════════════════════════════════════════════════════
    ("PMLA_BO_001","Beneficial Owner Identification for Companies","PMLA","beneficial_ownership","RBI_PMLA_2023","2023-10-17",
     [{"field":"customer_type","operator":"equals","value":"company"}],
     [{"type":"limit","field":"beneficial_ownership_threshold","value":25,"description":"Natural persons with 25%+ voting rights/share capital in a company are Beneficial Owners"}],
     [],
     [],
     "For companies, any natural person who ultimately owns or controls 25% or more of the shares, voting rights, or share capital must be identified as a Beneficial Owner (BO). Their KYC must be completed including identity, address, and nature of control.",
     ["PMLA","beneficial_ownership","company","25_percent","KYC"],["PMLA_BO_002","KYC_AK_003"]),

    ("PMLA_BO_002","Beneficial Owner for Trust","PMLA","beneficial_ownership","RBI_PMLA_2023","2023-10-17",
     [{"field":"customer_type","operator":"equals","value":"trust"}],
     [{"type":"procedure","field":"trust_BO","description":"Settlor, trustees, protector, beneficiaries (or class), and controlling persons of trusts must all be identified"}],
     [],
     [],
     "For trusts, the following persons must be identified and their KYC completed: the settlor (person who created the trust), all trustees, any protector, all beneficiaries or the class of beneficiaries, and any other natural person exercising ultimate control over the trust.",
     ["PMLA","beneficial_ownership","trust","settlor","trustee","beneficiary"],["PMLA_BO_001","KYC_CID_004"]),

    ("PMLA_BO_003","Senior Managing Official as BO Fallback","PMLA","beneficial_ownership","RBI_PMLA_2023","2023-10-17",
     [],
     [{"type":"procedure","field":"senior_official_fallback","description":"If no natural person qualifies as BO by ownership threshold, Senior Managing Official is deemed BO"}],
     [],
     [],
     "If no natural person meets the ownership threshold for Beneficial Owner identification (e.g., ownership is widely dispersed), the regulated entity must identify the senior managing official of the customer entity as the Beneficial Owner for KYC purposes.",
     ["PMLA","beneficial_ownership","senior_managing_official","fallback"],["PMLA_BO_001","KYC_CID_003"]),

    ("PMLA_BO_004","Annual BO Verification","PMLA","beneficial_ownership","RBI_PMLA_2023","2023-10-17",
     [],
     [{"type":"procedure","field":"BO_annual_verification","description":"Beneficial Owner information must be reverified at least annually for high-risk customers"}],
     [],
     [],
     "For high-risk customers, the Beneficial Owner information must be reverified at least annually. For medium-risk customers, verification should occur every 2 years. Any change in BO — such as a new shareholder crossing the threshold — must be updated immediately.",
     ["PMLA","beneficial_ownership","annual_verification","high_risk"],["PMLA_BO_001","KYC_RK_003"]),

    ("PMLA_BO_005","Ultimate Beneficial Owner Tracing for Listed Companies","PMLA","beneficial_ownership","RBI_PMLA_2023","2023-10-17",
     [{"field":"customer_type","operator":"equals","value":"listed_company"}],
     [],
     [{"condition":"Company listed on recognised stock exchange in India","outcome":"Beneficial ownership threshold and tracing rules are relaxed"}],
     [],
     "Companies listed on a recognised Indian stock exchange are exempt from the standard beneficial ownership tracing requirement for the listed entity itself, but the regulated entity must still identify and verify BOs for any unlisted subsidiaries or holding companies that form part of the customer relationship.",
     ["PMLA","beneficial_ownership","listed_company","stock_exchange","exemption"],["PMLA_BO_001"]),

    # ══════════════════════════════════════════════════════════
    # commercial_banks — capital_adequacy
    # ══════════════════════════════════════════════════════════
    ("CB_CA_001","Minimum CRAR Requirement","commercial_banks","capital_adequacy","RBI_BASEL3_2023","2023-05-12",
     [{"field":"bank_type","operator":"equals","value":"scheduled_commercial_bank"}],
     [{"type":"percentage_limit","field":"CRAR","value":9,"description":"Minimum Capital to Risk-Weighted Assets Ratio (CRAR) of 9% required at all times"}],
     [],
     [{"violation":"CRAR falls below 9%","action":"Prompt Corrective Action (PCA) framework triggered","reference":"RBI Basel III Circular 2023"}],
     "All Scheduled Commercial Banks must maintain a minimum Capital to Risk-Weighted Assets Ratio (CRAR) of 9% on an ongoing basis. This is higher than the Basel III minimum of 8% to provide an additional buffer for Indian market conditions.",
     ["commercial_banks","capital_adequacy","CRAR","Basel_III","PCA"],["CB_CA_002","CB_CA_003"]),

    ("CB_CA_002","Capital Conservation Buffer","commercial_banks","capital_adequacy","RBI_BASEL3_2023","2021-10-01",
     [{"field":"bank_type","operator":"equals","value":"scheduled_commercial_bank"}],
     [{"type":"percentage_limit","field":"CCB","value":2.5,"description":"Capital Conservation Buffer (CCB) of 2.5% of RWAs over and above minimum CRAR"}],
     [],
     [{"violation":"CCB falls below 2.5%","action":"Restrictions on dividend payouts and bonus payments","reference":"RBI Basel III Circular 2023 Para 15"}],
     "Banks must maintain a Capital Conservation Buffer (CCB) of 2.5% over and above the minimum 9% CRAR — effectively requiring a total CRAR of 11.5%. If the CCB falls below 2.5%, the bank faces automatic restrictions on distributing dividends, paying bonuses, or buying back shares.",
     ["commercial_banks","capital_adequacy","CCB","Basel_III","dividend"],["CB_CA_001","CB_CA_003"]),

    ("CB_CA_003","Common Equity Tier 1 Minimum","commercial_banks","capital_adequacy","RBI_BASEL3_2023","2023-05-12",
     [{"field":"bank_type","operator":"equals","value":"scheduled_commercial_bank"}],
     [{"type":"percentage_limit","field":"CET1","value":5.5,"description":"Common Equity Tier 1 (CET1) capital minimum of 5.5% of RWAs"}],
     [],
     [],
     "Banks must maintain Common Equity Tier 1 (CET1) capital — the highest quality capital consisting of paid-up equity and retained earnings — at a minimum of 5.5% of Risk-Weighted Assets (RWAs). Including the CCB, the effective CET1 requirement is 8%.",
     ["commercial_banks","capital_adequacy","CET1","Basel_III","Tier1"],["CB_CA_001","CB_CA_002"]),

    ("CB_CA_004","Tier 1 Capital Minimum","commercial_banks","capital_adequacy","RBI_BASEL3_2023","2023-05-12",
     [],
     [{"type":"percentage_limit","field":"Tier1_capital","value":7,"description":"Total Tier 1 capital (CET1 + Additional Tier 1) must be at least 7% of RWAs"}],
     [],
     [],
     "Total Tier 1 capital, which includes both Common Equity Tier 1 and Additional Tier 1 instruments, must be at least 7% of Risk-Weighted Assets at all times. Additional Tier 1 capital can constitute a maximum of 1.5% of RWAs.",
     ["commercial_banks","capital_adequacy","Tier1","AT1","Basel_III"],["CB_CA_001","CB_CA_003"]),

    ("CB_CA_005","ICAAP Quarterly Requirement","commercial_banks","capital_adequacy","RBI_BASEL3_2023","2023-05-12",
     [],
     [{"type":"procedure","field":"ICAAP","description":"Internal Capital Adequacy Assessment Process (ICAAP) must be conducted quarterly"}],
     [],
     [],
     "Banks must conduct an Internal Capital Adequacy Assessment Process (ICAAP) on a quarterly basis to assess whether their current capital levels are sufficient to cover all material risks, including risks not captured under Pillar I. ICAAP results must be reported to the Board.",
     ["commercial_banks","capital_adequacy","ICAAP","Pillar2","Basel_III"],["CB_CA_001","CB_GOV_001"]),

    # ══════════════════════════════════════════════════════════
    # commercial_banks — NPA
    # ══════════════════════════════════════════════════════════
    ("CB_NPA_001","NPA Classification — 90 Day Rule","commercial_banks","NPA","RBI_IRACP_2023","2023-04-01",
     [],
     [{"type":"procedure","field":"NPA_classification","value":90,"description":"Loan account overdue for more than 90 days becomes Non-Performing Asset"}],
     [{"condition":"Agricultural loans — overdue for two crop seasons","outcome":"Classified as NPA after two crop seasons"}],
     [],
     "A loan account where any amount of principal or interest is overdue for more than 90 consecutive days must be classified as a Non-Performing Asset (NPA). Banks must run system-based NPA classification daily. For agricultural loans, the NPA trigger is overdue for two crop seasons instead of 90 days.",
     ["commercial_banks","NPA","90_days","asset_classification","IRACP"],["CB_NPA_002","CB_NPA_003"]),

    ("CB_NPA_002","Substandard Asset Provisioning","commercial_banks","NPA","RBI_IRACP_2023","2023-04-01",
     [{"field":"asset_classification","operator":"equals","value":"substandard"}],
     [{"type":"percentage_limit","field":"provisioning","value":15,"description":"General provision of 15% on secured substandard assets; 25% on unsecured"}],
     [],
     [],
     "For Substandard Assets (NPAs of up to 12 months), banks must make a provision of 15% on secured portions and 25% on unsecured portions. This provision is the bank's estimate of the likely loss on the asset.",
     ["commercial_banks","NPA","substandard","provisioning","IRACP"],["CB_NPA_001","CB_NPA_003"]),

    ("CB_NPA_003","Loss Asset 100% Provisioning","commercial_banks","NPA","RBI_IRACP_2023","2023-04-01",
     [{"field":"asset_classification","operator":"equals","value":"loss"}],
     [{"type":"percentage_limit","field":"provisioning","value":100,"description":"100% provision required on loss assets"}],
     [],
     [],
     "Loss Assets are those where the bank has identified that there is virtually no chance of recovery. These must be fully provisioned at 100% of the outstanding amount. Loss Assets identified by RBI inspectors but not written off must remain on the books with 100% provisioning.",
     ["commercial_banks","NPA","loss_asset","provisioning","write_off"],["CB_NPA_001","CB_NPA_002"]),

    ("CB_NPA_004","SMA-0, SMA-1, SMA-2 Classification","commercial_banks","NPA","RBI_IRACP_2023","2023-04-01",
     [],
     [{"type":"procedure","field":"SMA_classification","description":"Special Mention Accounts: SMA-0 (1-30 days), SMA-1 (31-60 days), SMA-2 (61-90 days overdue)"}],
     [],
     [],
     "Before an account becomes NPA, it passes through Special Mention Account (SMA) stages: SMA-0 for 1-30 days overdue, SMA-1 for 31-60 days, and SMA-2 for 61-90 days overdue. Banks must monitor SMA accounts closely and initiate corrective action early to prevent NPA slippage.",
     ["commercial_banks","NPA","SMA","early_warning","IRACP"],["CB_NPA_001"]),

    ("CB_NPA_005","Standard Asset Provision Requirement","commercial_banks","NPA","RBI_IRACP_2023","2023-04-01",
     [{"field":"asset_classification","operator":"equals","value":"standard"}],
     [{"type":"percentage_limit","field":"standard_provisioning","value":0.4,"description":"Provision of 0.40% on all standard assets (to be achieved by March 31, 2025)"}],
     [],
     [],
     "Banks must maintain a general provision of 0.40% on all standard (performing) assets as a buffer against future losses. This provision is not against any specific loan but is a portfolio-level reserve. The requirement is being phased in: 0.30% by March 2024, 0.35% by September 2024, and 0.40% by March 2025.",
     ["commercial_banks","NPA","standard_asset","provisioning","phased_implementation"],["CB_NPA_001","CB_CA_001"]),

    # ══════════════════════════════════════════════════════════
    # commercial_banks — interest_rate
    # ══════════════════════════════════════════════════════════
    ("CB_IR_001","MCLR Methodology","commercial_banks","interest_rate","RBI_MCLR_2016","2016-04-01",
     [{"field":"bank_type","operator":"equals","value":"scheduled_commercial_bank"}],
     [{"type":"procedure","field":"MCLR_calculation","description":"MCLR = Marginal Cost of Funds + Negative CRR Carry + Operating Cost + Tenor Premium"}],
     [],
     [],
     "The Marginal Cost of Funds Based Lending Rate (MCLR) is the minimum interest rate below which a bank cannot lend (with certain exceptions). It is calculated as: Marginal Cost of Funds + Cost of maintaining Cash Reserve Ratio + Operating Costs + Tenor Premium. Banks must publish their MCLR for different tenors monthly.",
     ["commercial_banks","interest_rate","MCLR","lending_rate","pricing"],["CB_IR_002","CB_IR_003"]),

    ("CB_IR_002","External Benchmark Lending Rate for Retail","commercial_banks","interest_rate","RBI_EBLR_2019","2019-10-01",
     [{"field":"loan_category","operator":"in","value":"retail,MSME"}],
     [{"type":"procedure","field":"EBLR_mandatory","description":"Floating rate loans to retail and MSME borrowers must be linked to external benchmark"}],
     [],
     [],
     "All floating rate loans to retail and MSME borrowers must be linked to an external benchmark — either RBI's Repo Rate, or 3-month/6-month Treasury Bill yields published by FBIL. Banks cannot use their internal MCLR for floating rate retail or MSME loans.",
     ["commercial_banks","interest_rate","EBLR","repo_rate","retail","MSME"],["CB_IR_001"]),

    ("CB_IR_003","Reset Periodicity Maximum One Year","commercial_banks","interest_rate","RBI_MCLR_2016","2016-04-01",
     [],
     [{"type":"procedure","field":"interest_reset","value":1,"description":"Interest rate reset period for MCLR-linked loans shall not exceed one year"}],
     [],
     [],
     "For MCLR-linked loans, the interest rate reset period — the period after which the bank can change the applicable interest rate — shall not exceed one year. The exact reset period must be specified in the loan agreement and cannot be changed unilaterally by the bank.",
     ["commercial_banks","interest_rate","MCLR","reset_period","loan_terms"],["CB_IR_001"]),

    ("CB_IR_004","No Penal Interest — Penalty Only","commercial_banks","interest_rate","RBI_PENAL_2023","2024-01-01",
     [],
     [],
     [],
     [{"violation":"Charging penal interest (capitalising penalties) on loan default","action":"Regulatory action and customer refund","reference":"RBI Circular DOR.MCS.REC.28/01.01.001/2023-24"}],
     "Banks cannot charge penal interest rates on loan defaults. As of January 1, 2024, banks may only levy a reasonable penal charge (flat fee or percentage of overdue amount) which cannot be capitalised — i.e., it cannot be added to the outstanding principal or compound. This prevents the cascade of mounting interest on interest.",
     ["commercial_banks","interest_rate","penal_charge","loan_default","consumer_protection"],["CB_IR_001","CB_NPA_001"]),

    ("CB_IR_005","Interest on Savings Accounts Minimum","commercial_banks","interest_rate","RBI_SAVINGS_2011","2011-10-25",
     [],
     [{"type":"procedure","field":"savings_rate_deregulated","description":"Banks free to set savings deposit rates; must pay interest at uniform rate on similar balances"}],
     [],
     [],
     "Savings account interest rates are deregulated — banks can set their own rates. However, they must pay interest at a uniform rate on deposits up to ₹1 lakh, and a different uniform rate on deposits above ₹1 lakh. They cannot offer different rates to different customers with similar balances.",
     ["commercial_banks","interest_rate","savings_account","deregulation","uniformity"],["CB_IR_001"]),

    # ══════════════════════════════════════════════════════════
    # commercial_banks — deposits
    # ══════════════════════════════════════════════════════════
    ("CB_DEP_001","DICGC Deposit Insurance Limit","commercial_banks","deposits","RBI_DICGC_2020","2020-02-04",
     [],
     [{"type":"limit","field":"deposit_insurance","value":500000,"currency":"INR","description":"DICGC insures each depositor up to ₹5 lakh per bank"}],
     [],
     [],
     "The Deposit Insurance and Credit Guarantee Corporation (DICGC) insures each depositor for up to ₹5 lakh per bank, covering both principal and interest. This covers savings, fixed, recurring, and current deposit accounts. If a bank fails, each depositor gets up to ₹5 lakh even if their total deposits exceed this amount.",
     ["commercial_banks","deposits","DICGC","deposit_insurance","safety"],["CB_DEP_002"]),

    ("CB_DEP_002","Fixed Deposit Premature Withdrawal","commercial_banks","deposits","RBI_FD_2020","2020-04-01",
     [],
     [{"type":"procedure","field":"premature_withdrawal","description":"Banks must allow premature withdrawal of FDs; may levy a penalty not exceeding 1% of contracted rate"}],
     [],
     [],
     "Banks must allow premature withdrawal of Fixed Deposits. They may charge a penalty for premature withdrawal, but this penalty cannot exceed 1% of the contracted interest rate. Banks must clearly disclose their premature withdrawal penalty in the FD agreement and on their website.",
     ["commercial_banks","deposits","FD","premature_withdrawal","penalty"],["CB_DEP_001"]),

    ("CB_DEP_003","Inoperative Account Activation","commercial_banks","deposits","RBI_INACTIVE_2023","2023-04-01",
     [{"field":"account_status","operator":"equals","value":"inoperative"}],
     [{"type":"procedure","field":"activation_process","description":"Inoperative accounts (2+ years dormant) must be activated through KYC re-verification"}],
     [],
     [],
     "A savings or current account that has had no customer-initiated transactions for 2 years becomes 'inoperative'. Banks must activate inoperative accounts only after re-verifying the customer's KYC. Banks cannot levy maintenance charges on inoperative accounts.",
     ["commercial_banks","deposits","inoperative_account","dormant","KYC"],["CB_DEP_001","KYC_RK_001"]),

    ("CB_DEP_004","Unclaimed Deposits Transfer to RBI","commercial_banks","deposits","RBI_UDGAM_2023","2023-06-01",
     [{"field":"deposit_dormant_years","operator":"greater_than","value":10}],
     [{"type":"procedure","field":"UDGAM_transfer","description":"Unclaimed deposits dormant for 10+ years must be transferred to RBI's Depositor Education and Awareness Fund"}],
     [],
     [],
     "Deposits that remain unclaimed for 10 years or more must be transferred to RBI's Depositor Education and Awareness Fund (DEAF). The original depositor can still claim the deposit from the bank after transfer; the bank is then reimbursed from DEAF. Banks must actively publicise unclaimed deposit search through RBI's UDGAM portal.",
     ["commercial_banks","deposits","unclaimed_deposits","DEAF","UDGAM"],["CB_DEP_003"]),

    ("CB_DEP_005","NRE Account Repatriation Rights","commercial_banks","deposits","RBI_FEMA_2000","2000-05-03",
     [{"field":"account_type","operator":"equals","value":"NRE"}],
     [],
     [],
     [],
     "Non-Resident External (NRE) accounts are fully repatriable — the principal and interest can be freely transferred abroad without any limit or RBI approval. NRE accounts are maintained in Indian Rupees but represent foreign earnings. Both principal and interest are exempt from Indian income tax.",
     ["commercial_banks","deposits","NRE","repatriation","FEMA","NRI"],["CB_DEP_001"]),

    # ══════════════════════════════════════════════════════════
    # commercial_banks — credit
    # ══════════════════════════════════════════════════════════
    ("CB_CR_001","Single Borrower Exposure Limit","commercial_banks","credit","RBI_EXPOSURE_2019","2019-06-03",
     [],
     [{"type":"percentage_limit","field":"single_borrower_exposure","value":15,"description":"Credit exposure to a single borrower must not exceed 15% of eligible capital base"}],
     [{"condition":"For infrastructure projects with board approval","outcome":"Exposure limit may be extended to 20%"}],
     [{"violation":"Exposure exceeds 15% of capital base","action":"Excess to be reported to RBI; board approval required","reference":"RBI Large Exposure Framework 2019"}],
     "A bank's credit exposure to any single borrower must not exceed 15% of its eligible capital base (Tier 1 + Tier 2 capital). For infrastructure projects, this limit may be extended to 20% with board approval. Group exposures are counted on a consolidated basis.",
     ["commercial_banks","credit","single_borrower","exposure_limit","large_exposure"],["CB_CR_002","CB_CA_001"]),

    ("CB_CR_002","Group Borrower Exposure Limit","commercial_banks","credit","RBI_EXPOSURE_2019","2019-06-03",
     [],
     [{"type":"percentage_limit","field":"group_exposure","value":25,"description":"Total exposure to a group of connected borrowers shall not exceed 25% of eligible capital base"}],
     [],
     [],
     "Total credit exposure to a group of connected borrowers (companies under common ownership or control) must not exceed 25% of the bank's eligible capital base. The bank must identify all connected borrowers and aggregate their exposures before sanctioning new credit.",
     ["commercial_banks","credit","group_exposure","connected_borrowers","large_exposure"],["CB_CR_001"]),

    ("CB_CR_003","Priority Sector Lending Target","commercial_banks","credit","RBI_PSL_2020","2020-09-04",
     [{"field":"bank_type","operator":"equals","value":"domestic_scheduled_commercial_bank"}],
     [{"type":"percentage_limit","field":"PSL_target","value":40,"description":"40% of Adjusted Net Bank Credit (ANBC) must flow to priority sectors"}],
     [],
     [],
     "Domestic Scheduled Commercial Banks must ensure that 40% of their Adjusted Net Bank Credit (ANBC) or Credit Equivalent of Off-Balance Sheet Exposure goes to priority sectors: agriculture, MSME, export credit, education, housing, social infrastructure, and renewable energy.",
     ["commercial_banks","credit","priority_sector","PSL","agriculture","MSME"],["CB_CR_001"]),

    ("CB_CR_004","Loan Against Gold Jewellery LTV","commercial_banks","credit","RBI_GOLD_2020","2020-08-06",
     [{"field":"loan_type","operator":"equals","value":"gold_loan"}],
     [{"type":"percentage_limit","field":"LTV","value":75,"description":"Loan-to-Value ratio for gold loans shall not exceed 75% of gold value"}],
     [],
     [{"violation":"LTV exceeds 75%","action":"Excess advance to be recalled within 30 days","reference":"RBI Circular DOR.No.BP.BC.38/21.04.132/2020-21"}],
     "For loans against gold jewellery, the Loan-to-Value (LTV) ratio must not exceed 75% of the value of the gold at the time of sanctioning the loan. The gold must be appraised by a certified valuer. If gold prices fall and LTV exceeds 75%, the bank must ask the customer to bring in additional collateral or repay the excess.",
     ["commercial_banks","credit","gold_loan","LTV","collateral"],["CB_CR_001"]),

    ("CB_CR_005","Working Capital Loans — Drawing Power","commercial_banks","credit","RBI_IRACP_2023","2023-04-01",
     [{"field":"loan_type","operator":"equals","value":"working_capital_CC_OD"}],
     [{"type":"procedure","field":"drawing_power_review","description":"Stock statements for drawing power must not be older than 3 months"}],
     [],
     [{"violation":"Drawing power calculated from stock statements older than 3 months","action":"Account to be tagged as irregular","reference":"RBI IRACP Master Circular 2023 Para 2.1.3"}],
     "For working capital accounts (Cash Credit / Overdraft), the drawing power must be calculated from stock statements not older than 3 months. If a bank uses stock statements older than 3 months, the outstanding amount above the correctly calculated drawing power is treated as irregular, and the account may be classified as NPA if this continues for 90 days.",
     ["commercial_banks","credit","working_capital","drawing_power","stock_statement"],["CB_NPA_001","CB_CR_001"]),

    # ══════════════════════════════════════════════════════════
    # NBFC — registration
    # ══════════════════════════════════════════════════════════
    ("NBFC_REG_001","Certificate of Registration Mandatory","NBFC","registration","RBI_NBFC_SBR_2023","2023-10-19",
     [],
     [],
     [],
     [{"violation":"Operating as NBFC without COR","action":"Criminal prosecution under RBI Act Section 58B","reference":"RBI Act 1934 Section 45-IA"}],
     "No company can commence or carry on the business of a Non-Banking Financial Institution without obtaining a Certificate of Registration (COR) from RBI under Section 45-IA of the RBI Act. Operating as an NBFC without a COR is a criminal offence.",
     ["NBFC","registration","COR","RBI_Act","licensing"],["NBFC_REG_002"]),

    ("NBFC_REG_002","Minimum Net Owned Fund for Registration","NBFC","registration","RBI_NBFC_SBR_2023","2023-10-19",
     [],
     [{"type":"limit","field":"minimum_NOF","value":20000000,"currency":"INR","description":"Minimum Net Owned Fund of ₹2 crore required for NBFC registration"}],
     [],
     [],
     "An NBFC must have a minimum Net Owned Fund (NOF) of ₹2 crore to be eligible for registration with RBI. The NOF is the paid-up capital plus free reserves minus intangible assets and accumulated losses. New NBFC applicants must demonstrate this capital before applying for COR.",
     ["NBFC","registration","NOF","minimum_capital","₹2_crore"],["NBFC_REG_001","NBFC_PN_001"]),

    ("NBFC_REG_003","Scale-Based Regulation Categories","NBFC","registration","RBI_NBFC_SBR_2023","2023-10-19",
     [],
     [{"type":"procedure","field":"SBR_categories","description":"NBFCs categorised as Base Layer, Middle Layer, Upper Layer, Top Layer based on size and risk"}],
     [],
     [],
     "Under the Scale-Based Regulation (SBR) framework, NBFCs are classified into four layers: Base Layer (NBFC-BL), Middle Layer (NBFC-ML), Upper Layer (NBFC-UL), and Top Layer (NBFC-TL). Each layer has progressively stricter regulatory requirements. Classification is reviewed annually based on the NBFC's asset size, leverage, and systemic risk.",
     ["NBFC","registration","SBR","scale_based_regulation","classification"],["NBFC_REG_001","NBFC_PN_001"]),

    ("NBFC_REG_004","NBFC-D Public Deposit Ceiling","NBFC","registration","RBI_NBFC_SBR_2023","2023-10-19",
     [{"field":"NBFC_type","operator":"equals","value":"deposit_taking"}],
     [{"type":"percentage_limit","field":"public_deposits_limit","value":150,"description":"Deposit-taking NBFCs cannot accept deposits exceeding 1.5x their Net Owned Fund"}],
     [],
     [{"violation":"Public deposits exceed 1.5x NOF","action":"Excess deposits to be repaid; RBI action","reference":"RBI Master Direction NBFC 2023 Para 15"}],
     "Deposit-taking NBFCs (NBFC-D) cannot accept public deposits exceeding 1.5 times their Net Owned Fund. They must also maintain a minimum investment-grade credit rating from a RBI-approved rating agency to continue accepting public deposits.",
     ["NBFC","registration","public_deposits","deposit_ceiling","credit_rating"],["NBFC_REG_002","NBFC_PN_001"]),

    ("NBFC_REG_005","FATF Non-Compliant Jurisdiction Investment Limit","NBFC","registration","RBI_NBFC_SBR_2023","2023-10-19",
     [],
     [{"type":"percentage_limit","field":"FATF_non_compliant_investment","value":20,"description":"New investments from FATF non-compliant jurisdictions must be less than 20% of existing voting power"}],
     [],
     [],
     "NBFCs must not accept new investments from entities in jurisdictions identified by FATF as high-risk or non-compliant, unless such investment is less than 20% of the existing voting power. For jurisdictions under FATF's 'Call for Action' list, additional approval from RBI may be required.",
     ["NBFC","registration","FATF","foreign_investment","AML"],["NBFC_REG_001","AML_ST_001"]),

    # ══════════════════════════════════════════════════════════
    # NBFC — prudential_norms
    # ══════════════════════════════════════════════════════════
    ("NBFC_PN_001","NBFC-ML CRAR Requirement","NBFC","prudential_norms","RBI_NBFC_SBR_2023","2023-10-19",
     [{"field":"NBFC_layer","operator":"equals","value":"middle_layer"}],
     [{"type":"percentage_limit","field":"CRAR","value":15,"description":"NBFC-ML must maintain CRAR of minimum 15%"}],
     [],
     [{"violation":"CRAR falls below 15%","action":"Corrective action plan to be submitted within 30 days","reference":"RBI NBFC SBR Directions 2023 Chapter IV"}],
     "NBFC-Middle Layer entities must maintain a Capital to Risk-Weighted Assets Ratio (CRAR) of at least 15%. This is higher than the bank requirement of 9% to account for NBFCs' limited access to emergency liquidity support from RBI.",
     ["NBFC","prudential_norms","CRAR","capital_adequacy","middle_layer"],["NBFC_PN_002","NBFC_REG_002"]),

    ("NBFC_PN_002","NBFC NPA Classification — 90 Days","NBFC","prudential_norms","RBI_NBFC_SBR_2023","2023-10-19",
     [],
     [{"type":"procedure","field":"NPA_90_days","description":"NBFC loans overdue for more than 90 days to be classified as NPA"}],
     [{"condition":"NBFC not aligned to 90-day norm — refer SBR Directions","outcome":"Applicable norms under DoR.FIN.REC.No.45/03.10.119/2023-24"}],
     [],
     "NBFCs must classify loans as Non-Performing Assets (NPA) if the interest or principal is overdue for more than 90 days — the same standard as banks. NBFCs that have historically used different NPA recognition norms must transition to the 90-day standard as per the SBR Directions.",
     ["NBFC","prudential_norms","NPA","90_days","asset_classification"],["NBFC_PN_001","CB_NPA_001"]),

    ("NBFC_PN_003","NBFC Leverage Ratio Limit","NBFC","prudential_norms","RBI_NBFC_SBR_2023","2023-10-19",
     [{"field":"NBFC_layer","operator":"equals","value":"base_layer"}],
     [{"type":"limit","field":"leverage_ratio","value":7,"description":"Base Layer NBFCs must not exceed leverage ratio of 7x (Total Assets / Owned Fund)"}],
     [],
     [{"violation":"Leverage ratio exceeds 7x","action":"No new borrowings permitted until ratio is brought within limits","reference":"RBI NBFC SBR Directions 2023 Chapter IV"}],
     "Base Layer NBFCs must maintain a leverage ratio (Total Assets divided by Owned Fund) of no more than 7. This means an NBFC with ₹100 crore of owned funds cannot grow its balance sheet beyond ₹700 crore. Middle Layer NBFCs have tighter restrictions.",
     ["NBFC","prudential_norms","leverage","balance_sheet","borrowing_limit"],["NBFC_PN_001","NBFC_REG_002"]),

    ("NBFC_PN_004","NBFC Provisioning — Standard Assets","NBFC","prudential_norms","RBI_NBFC_SBR_2023","2023-10-19",
     [],
     [{"type":"percentage_limit","field":"standard_asset_provision","value":0.4,"description":"NBFCs must maintain 0.40% provision on all standard assets"}],
     [],
     [],
     "NBFCs must maintain a general provision of 0.40% on all standard (performing) assets as a contingency buffer. This provision is held at portfolio level and is not counted as Tier 2 capital. It must be included in the balance sheet under 'Other Funds and Reserves'.",
     ["NBFC","prudential_norms","provisioning","standard_asset","buffer"],["NBFC_PN_001","CB_NPA_005"]),

    ("NBFC_PN_005","NBFC Minimum Disclosure Requirements","NBFC","prudential_norms","RBI_NBFC_SBR_2023","2023-10-19",
     [],
     [{"type":"procedure","field":"annual_disclosure","description":"NBFC-ML and above must disclose CRAR, NPA ratios, and risk metrics in annual report"}],
     [],
     [],
     "NBFC-ML and NBFC-UL must make specific disclosures in their annual reports and websites, including CRAR, gross and net NPA ratios, liquidity ratios, and any regulatory penalties received during the year. These disclosures must be made within 21 days of annual accounts adoption.",
     ["NBFC","prudential_norms","disclosure","transparency","annual_report"],["NBFC_PN_001","CB_GOV_002"]),

    # ══════════════════════════════════════════════════════════
    # NBFC — fair_practices
    # ══════════════════════════════════════════════════════════
    ("NBFC_FP_001","Fair Practices Code Mandatory","NBFC","fair_practices","RBI_NBFC_FPC_2011","2011-09-28",
     [],
     [{"type":"procedure","field":"FPC_board_approval","description":"Fair Practices Code must be board-approved and published on NBFC's website"}],
     [],
     [],
     "Every NBFC must adopt a Board-approved Fair Practices Code (FPC) governing its lending practices, customer communication, interest rate policy, and grievance redressal. The FPC must be published on the NBFC's website and provided to customers in the local language on request.",
     ["NBFC","fair_practices","FPC","consumer_protection","transparency"],["NBFC_FP_002","NBFC_FP_003"]),

    ("NBFC_FP_002","Sanction Letter in Vernacular","NBFC","fair_practices","RBI_NBFC_FPC_2011","2011-09-28",
     [],
     [{"type":"procedure","field":"sanction_letter","description":"Loan sanction letters must be provided in vernacular language and include all key terms"}],
     [],
     [],
     "NBFCs must issue loan sanction letters to borrowers in the vernacular (local) language. The sanction letter must clearly state the loan amount, interest rate, tenor, repayment schedule, any processing fees, and the total cost of the loan expressed as an Annual Percentage Rate (APR).",
     ["NBFC","fair_practices","sanction_letter","vernacular","transparency"],["NBFC_FP_001"]),

    ("NBFC_FP_003","Grievance Redressal Officer Appointment","NBFC","fair_practices","RBI_NBFC_FPC_2011","2023-10-19",
     [],
     [{"type":"procedure","field":"grievance_officer","description":"NBFC must designate a Grievance Redressal Officer and publicise their contact details"}],
     [],
     [],
     "Every NBFC must designate a Grievance Redressal Officer and publish their name, phone number, and email address on the NBFC's website and in all loan documents. Customer complaints must be acknowledged within 5 working days and resolved within 30 days.",
     ["NBFC","fair_practices","grievance_redressal","consumer_protection"],["NBFC_FP_001"]),

    ("NBFC_FP_004","No Coercive Recovery Practices","NBFC","fair_practices","RBI_NBFC_FPC_2011","2011-09-28",
     [],
     [],
     [],
     [{"violation":"Employing coercive recovery agents or harassment","action":"RBI cancellation of COR; criminal action","reference":"RBI Fair Practices Code 2011 Para 6"}],
     "NBFCs must not use intimidation, harassment, or coercive methods for loan recovery. Recovery agents must not visit borrowers before 7 AM or after 7 PM. The NBFC is liable for the conduct of its recovery agents and must have a grievance mechanism for complaints against recovery staff.",
     ["NBFC","fair_practices","recovery","harassment","consumer_protection"],["NBFC_FP_001","NBFC_FP_003"]),

    ("NBFC_FP_005","No Discrimination in Credit Decisions","NBFC","fair_practices","RBI_NBFC_FPC_2011","2011-09-28",
     [],
     [],
     [],
     [],
     "NBFCs must not discriminate in credit decisions based on gender, religion, caste, or disability. Credit decisions must be based solely on the borrower's creditworthiness, repayment capacity, and the collateral offered. NBFCs must publish their credit appraisal criteria on their websites.",
     ["NBFC","fair_practices","non_discrimination","credit_decision","equal_opportunity"],["NBFC_FP_001"]),

    # ══════════════════════════════════════════════════════════
    # payment_banks — operations
    # ══════════════════════════════════════════════════════════
    ("PB_OPS_001","Payment Bank Deposit Limit","payment_banks","operations","RBI_PB_2014","2014-11-27",
     [{"field":"account_type","operator":"equals","value":"payment_bank_account"}],
     [{"type":"limit","field":"max_deposit","value":200000,"currency":"INR","description":"Payment Banks cannot hold more than ₹2 lakh per customer"}],
     [],
     [{"violation":"Customer deposit balance exceeds ₹2 lakh","action":"Excess funds to be transferred to linked bank account","reference":"RBI Payment Bank Guidelines 2014 Para 10"}],
     "Payment Banks can accept deposits from customers but cannot hold more than ₹2 lakh per individual customer at any time. Excess amounts must be automatically transferred to the customer's linked scheduled commercial bank account.",
     ["payment_banks","operations","deposit_limit","₹2_lakh"],["PB_OPS_002","PB_OPS_003"]),

    ("PB_OPS_002","Payment Bank Cannot Grant Loans","payment_banks","operations","RBI_PB_2014","2014-11-27",
     [{"field":"entity_type","operator":"equals","value":"payment_bank"}],
     [],
     [],
     [{"violation":"Payment Bank issuing loans or credit products","action":"COR cancellation","reference":"RBI Payment Bank Guidelines 2014 Para 5"}],
     "Payment Banks are not permitted to grant loans or advances of any kind. They cannot issue credit cards and cannot engage in any lending activity. Their role is restricted to accepting deposits, issuing prepaid payment instruments, and providing payment and remittance services.",
     ["payment_banks","operations","no_lending","prohibition","credit"],["PB_OPS_001"]),

    ("PB_OPS_003","Payment Bank Capital Requirement","payment_banks","operations","RBI_PB_2014","2014-11-27",
     [],
     [{"type":"limit","field":"minimum_capital","value":1000000000,"currency":"INR","description":"Minimum paid-up capital of ₹100 crore required for Payment Banks"}],
     [],
     [],
     "Payment Banks must have a minimum paid-up capital of ₹100 crore. They must maintain this capital on an ongoing basis. The minimum capital requirement is higher than regular NBFCs to reflect the systemic importance of payment services.",
     ["payment_banks","operations","capital_requirement","₹100_crore"],["PB_OPS_001"]),

    ("PB_OPS_004","Payment Bank Investment of Deposits","payment_banks","operations","RBI_PB_2014","2014-11-27",
     [],
     [{"type":"percentage_limit","field":"deposit_investment","value":75,"description":"75% of demand deposit balances must be invested in government securities"}],
     [],
     [],
     "Payment Banks must invest at least 75% of their demand deposit balances in Statutory Liquidity Ratio (SLR)-eligible government securities with maturity up to one year. The remaining 25% may be held in time/fixed deposits with scheduled commercial banks.",
     ["payment_banks","operations","SLR","government_securities","investment"],["PB_OPS_001","PB_OPS_003"]),

    ("PB_OPS_005","Payment Bank Promoter Stake","payment_banks","operations","RBI_PB_2014","2014-11-27",
     [],
     [{"type":"percentage_limit","field":"promoter_stake","value":40,"description":"Promoters must hold at least 40% for first 5 years of operations"}],
     [],
     [],
     "Payment Bank promoters must hold a minimum stake of 40% in the Payment Bank for the first 5 years of operations. After 5 years, the stake may be brought down to 26% over a period of time as determined by RBI.",
     ["payment_banks","operations","promoter_stake","ownership","governance"],["PB_OPS_003","CB_GOV_001"]),

    # ══════════════════════════════════════════════════════════
    # payment_banks — KYC
    # ══════════════════════════════════════════════════════════
    ("PB_KYC_001","Full KYC PPI Balance Limit","payment_banks","KYC","RBI_PPI_2021","2021-08-27",
     [{"field":"PPI_type","operator":"equals","value":"full_KYC_PPI"}],
     [{"type":"limit","field":"max_balance","value":200000,"currency":"INR","description":"Full-KYC PPI balance cannot exceed ₹2 lakh"}],
     [],
     [],
     "Full-KYC Prepaid Payment Instruments (PPIs) — wallets and prepaid cards where the customer has completed full KYC — can hold a maximum balance of ₹2 lakh at any time. Full-KYC PPIs can be used for merchant payments, P2P transfers, and cash withdrawals.",
     ["payment_banks","KYC","PPI","full_KYC","balance_limit"],["PB_KYC_002","PB_OPS_001"]),

    ("PB_KYC_002","Small PPI Minimum KYC Limit","payment_banks","KYC","RBI_PPI_2021","2021-08-27",
     [{"field":"PPI_type","operator":"equals","value":"small_PPI"}],
     [{"type":"limit","field":"max_balance","value":10000,"currency":"INR","description":"Small PPIs (minimum detail KYC) can hold maximum ₹10,000"}],
     [],
     [],
     "Small PPIs — where customers have provided only basic details (name and mobile number) — can hold a maximum balance of ₹10,000. Small PPIs can only be used for merchant payments and cannot be used for P2P transfers or cash withdrawals.",
     ["payment_banks","KYC","PPI","small_PPI","₹10,000"],["PB_KYC_001"]),

    ("PB_KYC_003","PPI Interoperability Mandatory","payment_banks","KYC","RBI_PPI_2021","2021-08-27",
     [{"field":"PPI_type","operator":"equals","value":"full_KYC_PPI"}],
     [{"type":"procedure","field":"interoperability","description":"Full-KYC PPIs must be interoperable with UPI and card networks"}],
     [],
     [],
     "All Full-KYC PPIs must support interoperability — they must enable UPI linkage allowing the wallet to be used via third-party UPI apps, and prepaid cards must work on RuPay, Visa, or Mastercard networks. This allows customers to use their PPIs across any payment acceptance infrastructure.",
     ["payment_banks","KYC","PPI","UPI","interoperability"],["PB_KYC_001","PB_DP_001"]),

    ("PB_KYC_004","PPI for Foreign Nationals Pilot","payment_banks","KYC","RBI_PPI_2023_FEB","2023-02-10",
     [{"field":"customer_type","operator":"equals","value":"foreign_national"}],
     [{"type":"limit","field":"max_balance","value":200000,"currency":"INR","description":"Full-KYC PPIs may be issued to foreign nationals visiting India; balance cap ₹2 lakh"}],
     [],
     [],
     "As a pilot initiative (February 2023), full-KYC PPIs can be issued to foreign nationals visiting India at select international airports. These INR-denominated PPIs can be linked to UPI for merchant payments only. The balance cap is ₹2 lakh, and unused balances can be encashed in foreign currency on departure.",
     ["payment_banks","KYC","PPI","foreign_national","UPI","pilot"],["PB_KYC_001","PB_KYC_003"]),

    ("PB_KYC_005","AFA for PPI Transactions","payment_banks","KYC","RBI_PPI_2021","2021-08-27",
     [],
     [{"type":"procedure","field":"AFA_mandatory","description":"Additional Factor Authentication (OTP/PIN) required for all PPI wallet and cash transactions"}],
     [{"condition":"Small recurring payments up to ₹5,000 with prior customer consent","outcome":"AFA may be waived"}],
     [],
     "All PPI wallet payments and cash withdrawals require Additional Factor Authentication (AFA) — an OTP or PIN. RBI has permitted a limited exemption for small recurring payments of up to ₹5,000 only where the customer has given prior explicit consent for AFA waiver.",
     ["payment_banks","KYC","PPI","AFA","OTP","authentication"],["PB_KYC_001"]),

    # ══════════════════════════════════════════════════════════
    # payment_banks — digital_payments
    # ══════════════════════════════════════════════════════════
    ("PB_DP_001","UPI Transaction Limits","payment_banks","digital_payments","RBI_UPI_2023","2023-09-01",
     [],
     [{"type":"limit","field":"UPI_per_transaction","value":100000,"currency":"INR","description":"Standard UPI transaction limit ₹1 lakh per transaction"}],
     [{"condition":"Tax payments and IPO applications","outcome":"UPI limit extended to ₹5 lakh per transaction"}],
     [],
     "The standard UPI transaction limit is ₹1 lakh per transaction per day for most use cases. For specific high-value use cases — government tax payments, IPO applications, RBI retail direct investments, and medical/educational institutions — the limit is ₹5 lakh per transaction.",
     ["payment_banks","digital_payments","UPI","transaction_limit","₹1_lakh"],["PB_DP_002","PB_DP_003"]),

    ("PB_DP_002","UPI Lite Offline Transaction Limit","payment_banks","digital_payments","RBI_UPI_LITE_2024","2024-10-09",
     [{"field":"payment_mode","operator":"equals","value":"UPI_Lite_offline"}],
     [{"type":"limit","field":"per_transaction","value":500,"currency":"INR","description":"UPI Lite offline: ₹500 per transaction"},
      {"type":"limit","field":"total_instrument_limit","value":2000,"currency":"INR","description":"UPI Lite offline: ₹2,000 total on device at any time"}],
     [],
     [],
     "UPI Lite operates offline for small payments in areas with poor connectivity. Each offline transaction is capped at ₹500, and the total amount loaded on the UPI Lite instrument on any device cannot exceed ₹2,000 at any time. These limits are being enhanced as per October 2024 RBI policy statement.",
     ["payment_banks","digital_payments","UPI_Lite","offline","₹500"],["PB_DP_001"]),

    ("PB_DP_003","UPI 123Pay Limit for Feature Phones","payment_banks","digital_payments","RBI_UPI123_2021","2021-11-08",
     [{"field":"payment_channel","operator":"equals","value":"UPI_123Pay"}],
     [{"type":"limit","field":"per_transaction","value":10000,"currency":"INR","description":"UPI 123Pay (feature phone) per-transaction limit ₹10,000"}],
     [],
     [],
     "UPI 123Pay enables feature phone users (without smartphones) to make UPI payments through IVR, missed calls, or proximity sound. The per-transaction limit for UPI 123Pay is ₹10,000 (doubled from ₹5,000 as of 2026 enhancement). This service is available 24x7 in multiple languages.",
     ["payment_banks","digital_payments","UPI_123Pay","feature_phone","financial_inclusion"],["PB_DP_001"]),

    ("PB_DP_004","Data Localisation for Payment Data","payment_banks","digital_payments","RBI_DATA_LOCALISATION_2018","2018-04-06",
     [],
     [],
     [],
     [{"violation":"Payment data stored outside India without prior RBI approval","action":"Regulatory action and potential cancellation of authorisation","reference":"RBI Payment Storage Circular 2018"}],
     "All data related to payment systems operated in India must be stored only within India. Payment system operators cannot store, process, or transmit Indian payment data to servers located outside India. Foreign entities may maintain a mirror copy outside India only for a limited period for purposes of cross-border transaction settlement.",
     ["payment_banks","digital_payments","data_localisation","data_storage","PDPB"],["PB_DP_001","PB_KYC_001"]),

    ("PB_DP_005","Payment Aggregator Merchant CDD","payment_banks","digital_payments","RBI_PA_2025","2025-09-15",
     [{"field":"entity_type","operator":"equals","value":"payment_aggregator"}],
     [{"type":"procedure","field":"merchant_CDD","description":"Payment Aggregators must conduct Customer Due Diligence on all onboarded merchants"}],
     [],
     [],
     "Under the 2025 PA Directions, Payment Aggregators must conduct Customer Due Diligence (CDD) on all merchants they onboard — verifying the merchant's identity, business legitimacy, ownership structure, and transaction patterns. This requirement was absent in the 2020 guidelines and significantly expands PA compliance obligations.",
     ["payment_banks","digital_payments","payment_aggregator","merchant_CDD","KYC"],["PB_DP_001","PB_KYC_001"]),

    # ══════════════════════════════════════════════════════════
    # forex — FEMA
    # ══════════════════════════════════════════════════════════
    ("FOREX_FEMA_001","LRS Annual Limit","forex","FEMA","RBI_LRS_2023","2023-05-11",
     [{"field":"remitter_type","operator":"equals","value":"resident_individual"}],
     [{"type":"limit","field":"LRS_annual_limit","value":250000,"currency":"USD","description":"Resident individuals can remit up to USD 250,000 per financial year under LRS"}],
     [],
     [],
     "Under the Liberalised Remittance Scheme (LRS), resident individuals (including minors with parent/guardian authorisation) can freely remit up to USD 250,000 per financial year for any permissible current or capital account transaction — including education, travel, medical treatment, investments abroad, and gifts.",
     ["forex","FEMA","LRS","remittance","USD_250000","resident_individual"],["FOREX_FEMA_002","FOREX_FEMA_003"]),

    ("FOREX_FEMA_002","TCS on LRS Remittances","forex","FEMA","RBI_LRS_2023","2023-07-01",
     [{"field":"remittance_purpose","operator":"not_equals","value":"education_loan_from_bank"}],
     [{"type":"percentage_limit","field":"TCS_rate","value":20,"description":"TCS of 20% applicable on LRS remittances above ₹7 lakh (except education and medical)"}],
     [{"condition":"Overseas education funded by loan from recognised institution","outcome":"TCS rate of 0.5%"},
      {"condition":"Medical treatment abroad","outcome":"TCS rate of 5%"}],
     [],
     "Tax Collection at Source (TCS) of 20% applies on LRS remittances above ₹7 lakh per financial year per individual (effective July 2023). Exemptions: education abroad funded by a bank loan attracts only 0.5% TCS; medical treatment abroad attracts 5% TCS. The TCS can be set off against the remitter's income tax liability.",
     ["forex","FEMA","LRS","TCS","20%","tax"],["FOREX_FEMA_001"]),

    ("FOREX_FEMA_003","AD Category-I Bank Authorization","forex","FEMA","RBI_FEMA_1999","1999-06-01",
     [],
     [{"type":"procedure","field":"AD_authorization","description":"Only Authorised Dealer Category-I banks can handle full range of FEMA transactions"}],
     [],
     [{"violation":"Non-AD entity handling restricted FEMA transactions","action":"Penalty under FEMA Section 11","reference":"FEMA 1999 Section 10"}],
     "Only Authorised Dealer (AD) Category-I banks — those specifically licensed by RBI — can deal in all foreign exchange transactions including current account transactions, capital account transactions, and trade finance. Money changers and AD-II entities have a more limited scope.",
     ["forex","FEMA","AD_bank","authorised_dealer","licensing"],["FOREX_FEMA_001","FOREX_REM_001"]),

    ("FOREX_FEMA_004","Outward Remittance Purpose Code","forex","FEMA","RBI_FEMA_1999","2023-01-01",
     [],
     [{"type":"procedure","field":"purpose_code","description":"Form A2 with purpose code mandatory for all outward remittances"}],
     [],
     [],
     "All outward remittances must be accompanied by Form A2 declaring the purpose of the remittance and the applicable purpose code. The purpose code determines the regulatory treatment of the remittance, including applicable TCS rates and reporting requirements. Banks must satisfy themselves about the genuineness of the declared purpose.",
     ["forex","FEMA","Form_A2","purpose_code","outward_remittance"],["FOREX_FEMA_001","FOREX_REM_001"]),

    ("FOREX_FEMA_005","Import Payment Deadline","forex","FEMA","RBI_FEMA_IMP_2023","2023-01-01",
     [{"field":"transaction_type","operator":"equals","value":"import_payment"}],
     [{"type":"procedure","field":"import_settlement","value":6,"description":"Import payments must be settled within 6 months of shipment date"}],
     [],
     [{"violation":"Import payment not settled within 6 months","action":"Bank must report to RBI; extension request required","reference":"FEMA Current Account Transactions Rules"}],
     "Banks must ensure that payments for imports are settled within 6 months from the date of shipment. If payment is not made within 6 months, the bank must report the outstanding import to RBI and assist the customer in seeking an extension from the Authorised Dealer.",
     ["forex","FEMA","import_payment","settlement_period","trade_finance"],["FOREX_FEMA_003","FOREX_IMP_001"]),

    # ══════════════════════════════════════════════════════════
    # forex — remittance
    # ══════════════════════════════════════════════════════════
    ("FOREX_REM_001","NRE Account Repatriation Full","forex","remittance","RBI_FEMA_NRI_2010","2010-05-03",
     [{"field":"account_type","operator":"equals","value":"NRE"}],
     [],
     [],
     [],
     "Non-Resident External (NRE) accounts are fully repatriable without any restrictions on amount or frequency. The NRI can transfer any amount from their NRE account to their foreign account without seeking RBI permission. Interest on NRE deposits is also fully repatriable and is exempt from Indian income tax.",
     ["forex","remittance","NRE","NRI","repatriation","tax_exemption"],["FOREX_REM_002","FOREX_FEMA_001"]),

    ("FOREX_REM_002","NRO Account Repatriation Limit","forex","remittance","RBI_FEMA_NRI_2010","2010-05-03",
     [{"field":"account_type","operator":"equals","value":"NRO"}],
     [{"type":"limit","field":"NRO_repatriation","value":1000000,"currency":"USD","description":"NRO account repatriation limited to USD 1 million per financial year"}],
     [],
     [],
     "Funds in Non-Resident Ordinary (NRO) accounts — which hold Indian income of NRIs — can be repatriated up to USD 1 million per financial year after payment of applicable taxes. The NRI must submit a certificate from a Chartered Accountant confirming tax payment. Principal of NRO deposits is not freely repatriable.",
     ["forex","remittance","NRO","NRI","USD_1_million","repatriation"],["FOREX_REM_001","FOREX_FEMA_001"]),

    ("FOREX_REM_003","Inward Remittance FIRC Issuance","forex","remittance","RBI_FEMA_1999","2023-01-01",
     [],
     [{"type":"procedure","field":"FIRC_issuance","description":"Banks must issue Foreign Inward Remittance Certificate within 7 days of remittance credit"}],
     [],
     [],
     "For every inward foreign remittance received, the bank must issue a Foreign Inward Remittance Certificate (FIRC) to the beneficiary within 7 days of the remittance being credited. The FIRC serves as documentary evidence of the foreign exchange receipt and is required for various regulatory and tax purposes.",
     ["forex","remittance","FIRC","inward_remittance","documentation"],["FOREX_REM_001","FOREX_FEMA_003"]),

    ("FOREX_REM_004","Money Transfer Service Scheme Reporting","forex","remittance","RBI_MTSS_2023","2023-01-01",
     [{"field":"service_type","operator":"equals","value":"MTSS"}],
     [{"type":"limit","field":"per_transaction_MTSS","value":2500,"currency":"USD","description":"Each MTSS transaction capped at USD 2,500"}],
     [],
     [],
     "Under the Money Transfer Service Scheme (MTSS) for inward remittances, each transaction is capped at USD 2,500 (approximately ₹2 lakh). The total number of remittances credited to a beneficiary under MTSS cannot exceed 30 in a financial year. MTSS can only be used for personal remittances.",
     ["forex","remittance","MTSS","USD_2500","per_transaction_limit"],["FOREX_REM_001","FOREX_FEMA_001"]),

    ("FOREX_REM_005","Cross-Border UPI Remittance Countries","forex","remittance","RBI_UPI_CROSS_BORDER","2023-02-09",
     [],
     [{"type":"procedure","field":"UPI_cross_border","description":"UPI cross-border transactions permitted with linkages to Singapore PayNow, UAE, Bhutan, Nepal"}],
     [],
     [],
     "RBI has enabled cross-border UPI transactions with several countries through bilateral payment system linkages. Indian residents can send and receive payments with Singapore (via PayNow), UAE (via AANI), Bhutan, and Nepal. These transactions are governed by FEMA current account regulations and must comply with applicable LRS limits.",
     ["forex","remittance","UPI","cross_border","Singapore","UAE","PayNow"],["FOREX_REM_001","PB_DP_001"]),

    # ══════════════════════════════════════════════════════════
    # governance — board_composition
    # ══════════════════════════════════════════════════════════
    ("GOV_BC_001","Minimum Independent Directors","governance","board_composition","RBI_GOV_2021","2021-11-26",
     [{"field":"bank_type","operator":"in","value":"private_bank,foreign_bank,NBFC_UL"}],
     [{"type":"procedure","field":"independent_directors","description":"At least one-third of the board must be independent directors"}],
     [],
     [],
     "Private sector banks and Upper Layer NBFCs must have at least one-third of their Board of Directors as Independent Directors. Independent Directors cannot have any financial relationship with the bank other than their director fees, and must be approved by RBI before appointment.",
     ["governance","board_composition","independent_directors","one_third","private_bank"],["GOV_BC_002","GOV_BC_003"]),

    ("GOV_BC_002","MD and CEO Appointment RBI Approval","governance","board_composition","RBI_GOV_2021","2021-11-26",
     [{"field":"bank_type","operator":"in","value":"private_bank,NBFC_UL"}],
     [{"type":"procedure","field":"CEO_approval","description":"MD/CEO appointment requires prior approval of RBI; term capped at 15 years at same bank"}],
     [],
     [],
     "The appointment, reappointment, or termination of the MD & CEO of private sector banks and NBFC-UL entities requires prior approval from RBI. The MD & CEO cannot serve more than 15 years in total (consecutive or otherwise) at the same bank. This rule aims to prevent excessive concentration of power.",
     ["governance","board_composition","MD_CEO","approval","term_limit"],["GOV_BC_001","GOV_BC_003"]),

    ("GOV_BC_003","Promoter Shareholding Reduction Timeline","governance","board_composition","RBI_GOV_2021","2021-11-26",
     [{"field":"bank_type","operator":"equals","value":"private_bank"}],
     [{"type":"percentage_limit","field":"promoter_stake_15yr","value":15,"description":"Promoters of private banks must dilute stake to 15% within 15 years of commencement"}],
     [],
     [],
     "Promoters of private sector banks must progressively reduce their shareholding: to 40% within 5 years, to 26% within 10 years, and to 15% within 15 years of the bank's commencement of business. This prevents any individual or group from maintaining controlling ownership of a bank indefinitely.",
     ["governance","board_composition","promoter_dilution","private_bank","ownership"],["GOV_BC_001","PB_OPS_005"]),

    ("GOV_BC_004","Cooperative Bank Director Term Limit","governance","board_composition","RBI_BANKING_LAWS_2025","2025-08-01",
     [{"field":"bank_type","operator":"equals","value":"cooperative_bank"}],
     [{"type":"procedure","field":"director_term","value":10,"description":"Non-executive directors of cooperative banks can serve maximum 10 years"}],
     [],
     [],
     "Following the Banking Laws Amendment Act 2025, the maximum term for directors (other than the Chairperson and whole-time directors) in cooperative banks has been increased from 8 years to 10 years. This aligns with the 97th Constitutional Amendment and provides greater continuity in cooperative bank governance.",
     ["governance","board_composition","cooperative_bank","director_term","10_years"],["GOV_BC_001"]),

    ("GOV_BC_005","Fit and Proper Criteria for Directors","governance","board_composition","RBI_GOV_2021","2021-11-26",
     [],
     [{"type":"procedure","field":"fit_and_proper","description":"All directors must meet RBI fit and proper criteria and submit declarations annually"}],
     [],
     [],
     "Every director of a bank must meet RBI's 'Fit and Proper' criteria, which assess integrity, track record, competence, and financial soundness. Directors must submit annual declarations confirming continued compliance. RBI can direct the removal of a director who no longer meets these criteria.",
     ["governance","board_composition","fit_and_proper","director","RBI_approval"],["GOV_BC_001","GOV_BC_002"]),

    # ══════════════════════════════════════════════════════════
    # governance — audit
    # ══════════════════════════════════════════════════════════
    ("GOV_AUD_001","Statutory Audit Rotation","governance","audit","RBI_AUDIT_2021","2021-04-27",
     [{"field":"bank_type","operator":"in","value":"commercial_bank,NBFC_UL"}],
     [{"type":"procedure","field":"audit_rotation","value":3,"description":"Statutory auditors must be rotated every 3 years; cannot be reappointed for 6 years after rotation"}],
     [],
     [],
     "Statutory auditors of commercial banks and Upper Layer NBFCs must be rotated every 3 years (one term). After completing a term, the audit firm cannot be reappointed as statutory auditor of the same bank for 6 years. This mandatory rotation prevents over-familiarity and improves audit independence.",
     ["governance","audit","statutory_audit","rotation","independence"],["GOV_AUD_002","GOV_AUD_003"]),

    ("GOV_AUD_002","Internal Audit Independence","governance","audit","RBI_GOV_2021","2021-11-26",
     [],
     [{"type":"procedure","field":"internal_audit_independence","description":"Chief Internal Auditor must report functionally to Audit Committee of Board"}],
     [],
     [],
     "The Chief Internal Auditor (CIA) must have a direct reporting line to the Audit Committee of the Board (ACB) for functional matters, while administratively reporting to the MD & CEO. The CIA's appointment and removal requires concurrence of the ACB to ensure independence from management.",
     ["governance","audit","internal_audit","CIA","audit_committee"],["GOV_AUD_001","GOV_AUD_003"]),

    ("GOV_AUD_003","Audit Committee Composition","governance","audit","RBI_GOV_2021","2021-11-26",
     [],
     [{"type":"procedure","field":"ACB_composition","description":"Audit Committee of Board must have majority of independent directors; chaired by independent director"}],
     [],
     [],
     "The Audit Committee of the Board (ACB) must have a majority of independent directors and must be chaired by an independent director who is not the Chairperson of the Board. The ACB is responsible for oversight of financial reporting, internal controls, and the internal and external audit functions.",
     ["governance","audit","audit_committee","independent_directors","ACB"],["GOV_AUD_001","GOV_BC_001"]),

    ("GOV_AUD_004","Risk-Based Internal Audit","governance","audit","RBI_RBIA_2024","2024-01-01",
     [],
     [{"type":"procedure","field":"RBIA","description":"Banks must implement Risk-Based Internal Audit framework covering all significant risks"}],
     [],
     [],
     "Banks must implement a Risk-Based Internal Audit (RBIA) framework where the frequency and depth of internal audits are determined by the risk profile of each business unit or process. High-risk areas must be audited at least annually; medium-risk areas every 2 years; low-risk areas every 3 years.",
     ["governance","audit","RBIA","risk_based","internal_audit"],["GOV_AUD_002"]),

    ("GOV_AUD_005","Concurrent Audit for Large Transactions","governance","audit","RBI_CONCURRENT_2023","2023-01-01",
     [],
     [{"type":"procedure","field":"concurrent_audit","description":"Branches with large transaction volumes must have concurrent audit in place"}],
     [],
     [],
     "Branches dealing in high volumes of large transactions — particularly forex transactions, credit card operations, and treasury operations — must have concurrent audit in place. Concurrent auditors review transactions on a real-time or near-real-time basis, unlike statutory auditors who review post-facto.",
     ["governance","audit","concurrent_audit","high_volume","forex"],["GOV_AUD_001","FOREX_FEMA_003"]),

    # ══════════════════════════════════════════════════════════
    # governance — disclosure
    # ══════════════════════════════════════════════════════════
    ("GOV_DIS_001","Basel III Pillar 3 Disclosures","governance","disclosure","RBI_BASEL3_2023","2023-05-12",
     [{"field":"bank_type","operator":"equals","value":"scheduled_commercial_bank"}],
     [{"type":"procedure","field":"Pillar3_disclosure","description":"Quarterly Pillar 3 disclosures on risk exposures, CRAR, leverage, and liquidity must be published on bank website"}],
     [],
     [],
     "Scheduled Commercial Banks must publish quarterly Pillar 3 disclosures on their websites within 21 days of the end of each quarter. Disclosures must include CRAR composition, risk-weighted assets by category, leverage ratio, liquidity coverage ratio, and qualitative information about risk management.",
     ["governance","disclosure","Pillar3","Basel_III","quarterly","transparency"],["GOV_DIS_002","CB_CA_001"]),

    ("GOV_DIS_002","Annual Report Mandatory Disclosures","governance","disclosure","RBI_GOV_2021","2021-11-26",
     [],
     [{"type":"procedure","field":"annual_report","description":"Banks must disclose related party transactions, directors' fees, and regulatory penalties in annual report"}],
     [],
     [],
     "Banks' annual reports must include specific disclosures: all related party transactions approved by the board, aggregate remuneration paid to the MD/CEO and senior management, regulatory penalties received during the year, and an overview of the bank's risk appetite framework.",
     ["governance","disclosure","annual_report","related_party","penalties"],["GOV_DIS_001","GOV_AUD_001"]),

    ("GOV_DIS_003","Cybersecurity Incident Reporting","governance","disclosure","RBI_CYBER_2024","2024-01-01",
     [],
     [{"type":"procedure","field":"cyber_incident_reporting","description":"Cybersecurity incidents must be reported to RBI within 6 hours of detection"}],
     [],
     [{"violation":"Failure to report cyber incident within 6 hours","action":"Regulatory action under RBI Cybersecurity Directions","reference":"RBI Cyber Resilience Framework 2024"}],
     "All regulated entities must report cybersecurity incidents to RBI within 6 hours of detection, regardless of severity. A detailed incident report must follow within 24 hours. RBI must be updated until the incident is fully resolved.",
     ["governance","disclosure","cybersecurity","incident_reporting","6_hours"],["GOV_DIS_001"]),

    ("GOV_DIS_004","Whistle Blower Policy Mandatory","governance","disclosure","RBI_GOV_2021","2021-11-26",
     [],
     [{"type":"procedure","field":"whistle_blower","description":"Board-approved whistle blower policy with direct reporting channel to Audit Committee"}],
     [],
     [],
     "All banks and NBFC-ML/UL entities must have a Board-approved Whistle Blower Policy that provides employees a direct, confidential channel to report concerns about ethical violations, financial irregularities, or regulatory non-compliance directly to the Audit Committee, bypassing management.",
     ["governance","disclosure","whistle_blower","ethics","audit_committee"],["GOV_AUD_003","GOV_DIS_002"]),

    ("GOV_DIS_005","NPA Divergence Disclosure","governance","disclosure","RBI_NPA_DIVERGENCE_2019","2019-04-01",
     [{"field":"divergence_threshold","operator":"greater_than","value":15}],
     [],
     [],
     [],
     "If RBI's supervisory assessment of NPAs differs from the bank's reported NPAs by more than 15% of the bank's published net profit (or exceeds ₹1 crore for smaller entities), the bank must publicly disclose this divergence in its annual report within 30 days of receiving RBI's assessment.",
     ["governance","disclosure","NPA_divergence","RBI_inspection","transparency"],["GOV_DIS_001","CB_NPA_001"]),

    # ══════════════════════════════════════════════════════════
    # governance — risk_management
    # ══════════════════════════════════════════════════════════
    ("GOV_RM_001","ALCO Constitution Mandatory","governance","risk_management","RBI_ALM_2012","2012-03-08",
     [{"field":"bank_type","operator":"in","value":"scheduled_commercial_bank,NBFC_ML,NBFC_UL"}],
     [{"type":"procedure","field":"ALCO","description":"Asset Liability Management Committee (ALCO) must be constituted chaired by CEO or MD"}],
     [],
     [],
     "Banks and NBFC-ML/UL entities must constitute an Asset Liability Management Committee (ALCO) chaired by the CEO or MD. ALCO must meet at least monthly to review the bank's interest rate risk, liquidity risk, and funding profile. ALCO decisions must be reported to the Board quarterly.",
     ["governance","risk_management","ALCO","ALM","liquidity","interest_rate_risk"],["GOV_RM_002","GOV_BC_001"]),

    ("GOV_RM_002","Liquidity Coverage Ratio Requirement","governance","risk_management","RBI_LCR_2014","2023-01-01",
     [{"field":"bank_type","operator":"equals","value":"scheduled_commercial_bank"}],
     [{"type":"percentage_limit","field":"LCR","value":100,"description":"Liquidity Coverage Ratio (LCR) must be maintained at minimum 100%"}],
     [],
     [{"violation":"LCR falls below 100%","action":"Immediate reporting to RBI; Board level action required","reference":"RBI LCR Directions 2014"}],
     "Scheduled Commercial Banks must maintain a Liquidity Coverage Ratio (LCR) of at least 100%, meaning they must hold enough High Quality Liquid Assets (HQLA) to cover their total net cash outflows over a 30-day stress scenario. LCR must be reported daily to RBI.",
     ["governance","risk_management","LCR","liquidity","Basel_III","HQLA"],["GOV_RM_001","CB_CA_001"]),

    ("GOV_RM_003","Net Stable Funding Ratio","governance","risk_management","RBI_NSFR_2021","2021-10-01",
     [{"field":"bank_type","operator":"equals","value":"scheduled_commercial_bank"}],
     [{"type":"percentage_limit","field":"NSFR","value":100,"description":"Net Stable Funding Ratio (NSFR) minimum 100% — long-term stable funding must cover long-term assets"}],
     [],
     [],
     "The Net Stable Funding Ratio (NSFR) requires banks to maintain available stable funding (capital, long-term liabilities) at least equal to required stable funding (long-term assets, off-balance sheet commitments) — i.e., a minimum NSFR of 100%. NSFR is reported quarterly.",
     ["governance","risk_management","NSFR","stable_funding","liquidity","Basel_III"],["GOV_RM_002","GOV_RM_001"]),

    ("GOV_RM_004","Cyber Resilience Framework Implementation","governance","risk_management","RBI_CYBER_2024","2024-01-01",
     [],
     [{"type":"procedure","field":"cyber_governance","description":"Board-level Cyber Security Committee mandatory; annual cyber risk assessment required"}],
     [],
     [],
     "All regulated entities must implement the RBI Cyber Resilience and Digital Payment Security Framework. This requires a Board-level IT/Cyber Security Committee, an annual cyber risk assessment, a Board-approved Information Security Policy, and regular penetration testing of all internet-facing systems.",
     ["governance","risk_management","cybersecurity","cyber_resilience","Board","IT_security"],["GOV_DIS_003","GOV_BC_001"]),

    ("GOV_RM_005","Outsourcing Risk Management","governance","risk_management","RBI_OUTSOURCING_2023","2023-04-27",
     [],
     [{"type":"procedure","field":"outsourcing_oversight","description":"Board must approve outsourcing policy; outsourcing of core management functions prohibited"}],
     [],
     [],
     "Banks must have a Board-approved Outsourcing Policy governing all material outsourcing arrangements. Core management functions — including credit decisions, risk management oversight, and internal audit — cannot be outsourced. All outsourcing contracts must include clauses giving RBI access to the service provider's books and premises.",
     ["governance","risk_management","outsourcing","vendor_management","Board"],["GOV_AUD_001","GOV_BC_001"]),

]

# ─────────────────────────────────────────────────────────────
# CIRCULARS
# ─────────────────────────────────────────────────────────────
CIRCULARS = [
    ("RBI_KYC_2023_45","Master Direction – Know Your Customer (KYC) Directions 2016 (Updated October 2023)","KYC","2023-10-17",
     ["KYC","AML","PMLA"],
     ["KYC_SA_001","KYC_SA_002","KYC_SA_003","KYC_SA_004","KYC_SA_005",
      "KYC_RK_001","KYC_RK_002","KYC_RK_003","KYC_RK_004","KYC_RK_005",
      "KYC_VK_001","KYC_VK_002","KYC_VK_003","KYC_VK_004","KYC_VK_005",
      "KYC_AK_001","KYC_AK_002","KYC_AK_003","KYC_AK_004","KYC_AK_005",
      "KYC_CID_001","KYC_CID_002","KYC_CID_003","KYC_CID_004","KYC_CID_005",
      "AML_ST_001","AML_ST_002","AML_ST_003","AML_ST_004","AML_ST_005",
      "AML_CTR_001","AML_CTR_002","AML_CTR_003","AML_CTR_004","AML_CTR_005"]),

    ("RBI_PMLA_2023","PMLA Amendment – October 2023 KYC/AML/CFT Compliance","PMLA","2023-10-17",
     ["PMLA","AML","KYC"],
     ["PMLA_RK_001","PMLA_RK_002","PMLA_RK_003","PMLA_RK_004","PMLA_RK_005",
      "PMLA_BO_001","PMLA_BO_002","PMLA_BO_003","PMLA_BO_004","PMLA_BO_005"]),

    ("RBI_BASEL3_2023","Master Circular – Basel III Capital Regulations (Updated May 2023)","commercial_banks","2023-05-12",
     ["commercial_banks","capital_adequacy"],
     ["CB_CA_001","CB_CA_002","CB_CA_003","CB_CA_004","CB_CA_005",
      "GOV_RM_002","GOV_RM_003","GOV_DIS_001"]),

    ("RBI_IRACP_2023","Master Circular – Prudential Norms on Income Recognition, Asset Classification and Provisioning (April 2023)","commercial_banks","2023-04-01",
     ["commercial_banks","NPA"],
     ["CB_NPA_001","CB_NPA_002","CB_NPA_003","CB_NPA_004","CB_NPA_005",
      "CB_CR_005"]),

    ("RBI_MCLR_2016","Interest Rate on Advances – MCLR Framework (Updated 2024)","commercial_banks","2016-04-01",
     ["commercial_banks","interest_rate"],
     ["CB_IR_001","CB_IR_002","CB_IR_003","CB_IR_004","CB_IR_005"]),

    ("RBI_EXPOSURE_2019","Large Exposures Framework (June 2019)","commercial_banks","2019-06-03",
     ["commercial_banks","credit"],
     ["CB_CR_001","CB_CR_002"]),

    ("RBI_NBFC_SBR_2023","Master Direction – Non-Banking Financial Company – Scale Based Regulation Directions 2023","NBFC","2023-10-19",
     ["NBFC","commercial_banks"],
     ["NBFC_REG_001","NBFC_REG_002","NBFC_REG_003","NBFC_REG_004","NBFC_REG_005",
      "NBFC_PN_001","NBFC_PN_002","NBFC_PN_003","NBFC_PN_004","NBFC_PN_005",
      "NBFC_FP_001","NBFC_FP_002","NBFC_FP_003","NBFC_FP_004","NBFC_FP_005"]),

    ("RBI_PB_2014","Guidelines for Licensing of Payments Banks (November 2014, Updated)","payment_banks","2014-11-27",
     ["payment_banks"],
     ["PB_OPS_001","PB_OPS_002","PB_OPS_003","PB_OPS_004","PB_OPS_005"]),

    ("RBI_PPI_2021","Master Direction – Issuance and Operation of Prepaid Payment Instruments (August 2021)","payment_banks","2021-08-27",
     ["payment_banks","KYC"],
     ["PB_KYC_001","PB_KYC_002","PB_KYC_003","PB_KYC_004","PB_KYC_005",
      "PB_DP_001","PB_DP_002","PB_DP_003","PB_DP_004"]),

    ("RBI_PA_2025","Master Direction – Regulation of Payment Aggregators (September 2025)","payment_banks","2025-09-15",
     ["payment_banks","KYC"],
     ["PB_DP_005"]),

    ("RBI_FEMA_1999","Foreign Exchange Management Act – Master Directions (Updated 2023)","forex","1999-06-01",
     ["forex","FEMA"],
     ["FOREX_FEMA_001","FOREX_FEMA_002","FOREX_FEMA_003","FOREX_FEMA_004","FOREX_FEMA_005",
      "FOREX_REM_001","FOREX_REM_002","FOREX_REM_003","FOREX_REM_004","FOREX_REM_005"]),

    ("RBI_GOV_2021","Guidelines on Corporate Governance in Banks – November 2021","governance","2021-11-26",
     ["governance"],
     ["GOV_BC_001","GOV_BC_002","GOV_BC_003","GOV_BC_005",
      "GOV_AUD_001","GOV_AUD_002","GOV_AUD_003",
      "GOV_DIS_002","GOV_DIS_004",
      "GOV_RM_001","GOV_RM_005"]),

    ("RBI_CYBER_2024","RBI Master Direction on Cyber Resilience and Digital Payment Security (2024)","governance","2024-01-01",
     ["governance","payment_banks"],
     ["GOV_DIS_003","GOV_RM_004"]),
]

# ─────────────────────────────────────────────────────────────
# RELATIONSHIPS between rules
# ─────────────────────────────────────────────────────────────
RELATIONSHIPS = [
    ("KYC_SA_001","KYC_SA_002","depends_on","Small account balance limit and annual credit limit apply together"),
    ("KYC_SA_001","KYC_SA_003","depends_on","Balance and withdrawal limits are co-dependent restrictions on small accounts"),
    ("KYC_SA_005","KYC_CID_001","depends_on","Small account conversion requires full OVD-based KYC completion"),
    ("KYC_RK_001","KYC_RK_002","references","Medium risk periodicity extends low risk re-KYC interval"),
    ("KYC_RK_002","KYC_RK_003","references","High risk is stricter version of medium risk re-KYC framework"),
    ("KYC_VK_001","KYC_VK_002","depends_on","V-CIP video must be stored as per storage requirements"),
    ("KYC_AK_003","PMLA_BO_001","modifies","2023 amendment reduced beneficial ownership threshold from 15% to 10%"),
    ("AML_ST_001","AML_ST_002","depends_on","STR filing triggers tipping-off prohibition"),
    ("AML_CTR_001","AML_ST_001","references","Cash transactions may also be suspicious and require STR"),
    ("PMLA_RK_001","PMLA_RK_002","references","Transaction record retention and KYC retention have same 5-year period"),
    ("CB_CA_001","CB_CA_002","depends_on","CCB is an addition on top of minimum CRAR requirement"),
    ("CB_CA_002","CB_CA_003","depends_on","CET1 is a component of the overall CRAR including CCB"),
    ("CB_NPA_001","CB_NPA_002","depends_on","Substandard provisioning applies once 90-day NPA classification is made"),
    ("CB_NPA_002","CB_NPA_003","references","Loss asset provisioning is escalation of substandard provisioning"),
    ("CB_IR_001","CB_IR_002","modifies","EBLR replaces MCLR for retail and MSME floating rate loans"),
    ("CB_CR_001","CB_CR_002","depends_on","Group exposure includes individual borrower exposures"),
    ("NBFC_REG_001","NBFC_REG_002","depends_on","COR cannot be granted without minimum NOF of ₹2 crore"),
    ("NBFC_PN_001","NBFC_PN_002","depends_on","NBFC NPA classification determines provisioning requirements"),
    ("NBFC_FP_001","NBFC_FP_002","depends_on","Fair practices code includes sanction letter requirements"),
    ("PB_OPS_001","PB_KYC_001","depends_on","Payment bank deposit limit aligns with full-KYC PPI limit"),
    ("PB_KYC_001","PB_KYC_002","modifies","Full KYC PPI has higher limit than small PPI"),
    ("PB_DP_001","PB_DP_002","references","UPI Lite is offline subset of UPI transaction framework"),
    ("FOREX_FEMA_001","FOREX_FEMA_002","depends_on","TCS applies on LRS remittances above the threshold"),
    ("FOREX_REM_001","FOREX_REM_002","references","NRE and NRO accounts have different repatriation rights"),
    ("GOV_BC_001","GOV_BC_002","depends_on","CEO appointment oversight is part of broader board governance"),
    ("GOV_AUD_001","GOV_AUD_002","depends_on","Internal audit reports to audit committee; both require independence"),
    ("GOV_AUD_003","GOV_BC_001","depends_on","Audit committee requires majority of independent directors"),
    ("GOV_RM_001","GOV_RM_002","depends_on","ALCO manages LCR as part of ALM function"),
    ("GOV_RM_002","GOV_RM_003","references","LCR (short-term) and NSFR (long-term) are complementary liquidity measures"),
    ("CB_CA_001","GOV_RM_002","depends_on","Capital adequacy and liquidity coverage are both required simultaneously"),
    ("KYC_CID_004","AML_ST_001","depends_on","EDD for high-risk customers may result in STR filing"),
    ("AML_ST_001","PMLA_RK_001","depends_on","STR records must be maintained as per PMLA record keeping rules"),
    ("CB_CR_003","CB_CR_001","depends_on","Priority sector lending is subset of total credit exposure framework"),
    ("NBFC_FP_003","NBFC_FP_001","depends_on","Grievance redressal is part of fair practices code"),
]

# ─────────────────────────────────────────────────────────────
# TOPICS
# ─────────────────────────────────────────────────────────────
TOPICS = [
    ("KYC","Know Your Customer","#1D9E75",
     ["small_account","re_kyc","video_kyc","aadhaar_kyc","customer_identification"],
     ["AML","PMLA","commercial_banks"]),
    ("AML","Anti-Money Laundering","#D85A30",
     ["suspicious_transactions","cash_transactions","STR","CTR"],
     ["KYC","PMLA","governance"]),
    ("PMLA","Prevention of Money Laundering Act","#993556",
     ["record_keeping","beneficial_ownership","reporting"],
     ["KYC","AML","governance"]),
    ("commercial_banks","Commercial Banks","#378ADD",
     ["credit","deposits","NPA","capital_adequacy","interest_rate"],
     ["NBFC","governance","KYC"]),
    ("NBFC","Non-Banking Financial Companies","#7F77DD",
     ["registration","prudential_norms","fair_practices","systemic_risk"],
     ["commercial_banks","governance","KYC"]),
    ("payment_banks","Payment Banks","#1D9E75",
     ["operations","deposit_limits","KYC","digital_payments"],
     ["commercial_banks","KYC","forex"]),
    ("forex","Foreign Exchange","#7F77DD",
     ["FEMA","remittance","import_export","ECB"],
     ["commercial_banks","governance","payment_banks"]),
    ("governance","Governance","#888780",
     ["board_composition","audit","disclosure","risk_management"],
     ["commercial_banks","NBFC","KYC"]),
]

# ─────────────────────────────────────────────────────────────
# INIT CONNECTIONS
# ─────────────────────────────────────────────────────────────
def get_mongo_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        client.server_info()
    except Exception as e:
        print(f"MongoDB not reachable: {e}")
        sys.exit(1)
    db = client[MONGO_DB]
    # indexes
    db.rules.create_index([("rule_id", ASCENDING)], unique=True)
    db.rules.create_index([("topic", ASCENDING),("subtopic", ASCENDING)])
    db.circulars.create_index([("circular_id", ASCENDING)], unique=True)
    db.relationships.create_index([("from_rule_id", ASCENDING)])
    db.relationships.create_index([("to_rule_id", ASCENDING)])
    db.topics.create_index([("topic_id", ASCENDING)], unique=True)
    return db


def get_qdrant():
    client = QdrantClient(path=QDRANT_PATH)
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        print(f"Created Qdrant collection: {COLLECTION_NAME}")
    return client


def embed_and_upsert(qdrant, embedder, text: str, payload: dict) -> str:
    h     = hashlib.sha256(text.encode()).hexdigest()
    pt_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, h))
    existing = qdrant.retrieve(collection_name=COLLECTION_NAME, ids=[pt_id], with_payload=False)
    if not existing:
        vec = embedder.encode(text, normalize_embeddings=True).tolist()
        qdrant.upsert(collection_name=COLLECTION_NAME, points=[
            PointStruct(id=pt_id, vector=vec, payload={**payload,"content_hash":h,"ingested_at":NOW})
        ])
    return pt_id


# ─────────────────────────────────────────────────────────────
# SEED FUNCTIONS
# ─────────────────────────────────────────────────────────────
def seed_topics(db, qdrant, embedder):
    print("\n── Seeding topics ──")
    for (tid, label, color, subtopics, related) in TOPICS:
        doc = {
            "topic_id": tid, "label": label, "parent_topic": None,
            "subtopics": subtopics, "related_topics": related,
            "rule_count": sum(1 for r in RULES if r[2] == tid),
            "active_rule_count": sum(1 for r in RULES if r[2] == tid),
            "circular_ids": [c[0] for c in CIRCULARS if tid in c[4] or c[2] == tid],
            "last_updated": NOW,
            "visualization_meta": {"cluster_color": color, "node_size": "large", "x_hint": 0.5, "y_hint": 0.5},
        }
        try:
            db.topics.replace_one({"topic_id": tid}, doc, upsert=True)
        except Exception as e:
            print(f"  Topic {tid}: {e}")

        # embed topic summary
        text = f"Topic: {label}. Covers {label} compliance regulations. Subtopics: {', '.join(subtopics)}. Related: {', '.join(related)}."
        embed_and_upsert(qdrant, embedder, text, {
            "record_type":"topic","topic_id":tid,"topic_label":label,
            "related_topics":related,"is_active":True,"tags":[tid]+subtopics
        })
        print(f"  {tid}: {doc['rule_count']} rules")


def seed_circulars(db):
    print("\n── Seeding circulars ──")
    for (cid, title, topic, date, topics, rule_ids) in CIRCULARS:
        doc = {
            "circular_id": cid, "title": title, "issuing_authority": "RBI",
            "date": date, "topic": topic, "topics": topics,
            "rule_ids": rule_ids, "supersedes": [], "superseded_by": None,
            "is_active": True, "full_text_path": f"circulars/{cid}.pdf",
            "summary": f"{title} — {len(rule_ids)} compliance rules.",
            "_ingested_at": NOW,
        }
        try:
            db.circulars.replace_one({"circular_id": cid}, doc, upsert=True)
            print(f"  {cid}: {len(rule_ids)} rules")
        except Exception as e:
            print(f"  Circular {cid}: {e}")


def seed_rules(db, qdrant, embedder):
    print("\n── Seeding rules ──")
    ok = err = 0
    for row in RULES:
        (rule_id, title, topic, subtopic, source_circular_id, effective_date,
         conditions, requirements, exceptions, penalties,
         plain_language_summary, tags, related_rule_ids) = row

        color = TOPIC_COLORS.get(topic, "#888780")

        # embed text for vector search
        embed_text = f"{title}. {plain_language_summary} Topic: {topic}/{subtopic}. Tags: {', '.join(tags)}."
        chunk_id   = embed_and_upsert(qdrant, embedder, embed_text, {
            "record_type":"rule", "rule_id":rule_id, "circular_id":source_circular_id,
            "topic":topic, "subtopic":subtopic, "is_active":True, "tags":tags,
            "chunk_text":embed_text[:400],
        })

        doc = {
            "rule_id":                rule_id,
            "title":                  title,
            "topic":                  topic,
            "subtopic":               subtopic,
            "source_circular_id":     source_circular_id,
            "effective_date":         effective_date,
            "is_active":              True,
            "superseded_by":          None,
            "conditions":             conditions,
            "requirements":           requirements,
            "exceptions":             exceptions,
            "penalties":              penalties,
            "plain_language_summary": plain_language_summary,
            "tags":                   tags,
            "related_rule_ids":       related_rule_ids,
            "vec_chunk_ids":          [chunk_id],
            "section_number":         rule_id,
            "visualization_meta":     {"cluster_color":color,"node_label":title[:40],"cluster":topic},
            "_validation_warnings":   [],
            "_ingested_at":           NOW,
        }

        try:
            db.rules.replace_one({"rule_id": rule_id}, doc, upsert=True)
            ok += 1
        except Exception as e:
            print(f"  Rule {rule_id}: {e}")
            err += 1

    print(f"  Rules: {ok} ok, {err} errors")


def seed_relationships(db):
    print("\n── Seeding relationships ──")
    ok = err = 0
    for (from_id, to_id, rel_type, note) in RELATIONSHIPS:
        doc = {
            "_id":          f"rel__{from_id}__{rel_type}__{to_id}",
            "from_rule_id": from_id,
            "to_rule_id":   to_id,
            "type":         rel_type,
            "note":         note,
            "effective_date": None,
        }
        try:
            db.relationships.replace_one({"_id": doc["_id"]}, doc, upsert=True)
            ok += 1
        except Exception as e:
            print(f"  Rel {from_id}->{to_id}: {e}")
            err += 1
    print(f"  Relationships: {ok} ok, {err} errors")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("RBI Compliance DB Seed Script")
    print(f"MongoDB: {MONGO_URI} / {MONGO_DB}")
    print(f"Qdrant:  {QDRANT_PATH}")
    print("=" * 60)

    print("\nLoading embedding model…")
    embedder = SentenceTransformer(EMBED_MODEL)

    db     = get_mongo_db()
    qdrant = get_qdrant()

    seed_topics(db, qdrant, embedder)
    seed_circulars(db)
    seed_rules(db, qdrant, embedder)
    seed_relationships(db)

    print("\n" + "=" * 60)
    print("SEED COMPLETE")
    print(f"  Topics:        {db.topics.count_documents({})}")
    print(f"  Circulars:     {db.circulars.count_documents({})}")
    print(f"  Rules:         {db.rules.count_documents({})}")
    print(f"  Relationships: {db.relationships.count_documents({})}")
    print(f"  Vec points:    {qdrant.get_collection(COLLECTION_NAME).points_count}")
    print("=" * 60)

    # breakdown by topic
    print("\nRules per topic/subtopic:")
    for topic, _, color, subtopics, _ in TOPICS:
        count = db.rules.count_documents({"topic": topic})
        print(f"  {topic:<40} {count:>3} rules")
        for sub in subtopics:
            sc = db.rules.count_documents({"topic": topic, "subtopic": sub})
            if sc:
                print(f"    └─ {sub:<36} {sc:>3}")


if __name__ == "__main__":
    main()
