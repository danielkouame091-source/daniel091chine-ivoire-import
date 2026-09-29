"""Point d'entrée unique des modèles SQLAlchemy."""
from app.models.asset import AssetDisposal, AssetRevaluation, DepreciationEntry, FixedAsset
from app.models.audit import AuditLog
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.exercice import Exercice
from app.models.forecast import CashflowForecast
from app.models.freeze import (
    FreezeCascadeRule, FreezeEvent, FreezeTarget, TenantFreezeState,
)
from app.models.journal import Journal
from app.models.mobile_money import MmTransaction
from app.models.nlp import NlpFeedback, NlpPattern, NlpSuggestion
from app.models.payroll import (
    CnpsDeclaration, DgiDeclaration, Employee, FinancialStatement, Payslip,
)
from app.models.plan import Plan
from app.models.plan_comptable import PlanComptable
from app.models.purchase import (
    GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine,
    Supplier, SupplierInvoice, SupplierInvoiceLine, SupplierPayment,
)
from app.models.session import Session
from app.models.stock import (
    FifoLayer, Item, ItemCategory, StockInventory, StockInventoryLine,
    StockLevel, StockMovement, Warehouse,
)
from app.models.subscription import Subscription, SubscriptionPayment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppMessage

__all__ = [
    "AssetDisposal", "AssetRevaluation", "AuditLog",
    "CashflowForecast", "CnpsDeclaration", "DepreciationEntry", "DgiDeclaration",
    "Ecriture", "EcritureLigne", "Employee", "Exercice", "FifoLayer",
    "FinancialStatement", "FixedAsset", "FreezeCascadeRule", "FreezeEvent", "FreezeTarget",
    "GoodsReceipt", "GoodsReceiptLine",
    "Item", "ItemCategory", "Journal", "MmTransaction",
    "NlpFeedback", "NlpPattern", "NlpSuggestion", "Payslip", "Plan", "PlanComptable",
    "PurchaseOrder", "PurchaseOrderLine",
    "Session", "StockInventory", "StockInventoryLine", "StockLevel", "StockMovement",
    "Subscription", "SubscriptionPayment",
    "Supplier", "SupplierInvoice", "SupplierInvoiceLine", "SupplierPayment",
    "Tenant", "TenantFreezeState", "User", "Warehouse",
    "WhatsAppLink", "WhatsAppMessage",
]
