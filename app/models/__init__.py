"""Point d'entrée unique des modèles SQLAlchemy."""
from app.models.analytical import (
    AllocationKey, AllocationKeyLine, AnalyticalAxis, AnalyticalEntry,
    AnalyticalSection, Budget, BudgetConsumption, BudgetLine,
)
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
from app.models.sale import (
    CreditNote, CreditNoteLine, Customer, CustomerInvoice, CustomerInvoiceLine,
    CustomerPayment, DeliveryNote, DeliveryNoteLine, Quote, QuoteLine,
    SalesOrder, SalesOrderLine,
)
from app.models.session import Session
from app.models.stock import (
    FifoLayer, Item, ItemCategory, StockInventory, StockInventoryLine,
    StockLevel, StockMovement, Warehouse,
)
from app.models.subscription import Subscription, SubscriptionPayment
from app.models.tenant import Tenant
from app.models.treasury import (
    BankStatement, BankStatementLine, CashForecastWeek, CashPositionSnapshot,
    ReconciliationSession, TreasuryAccount,
)
from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppMessage

__all__ = [
    "AllocationKey", "AllocationKeyLine",
    "AnalyticalAxis", "AnalyticalEntry", "AnalyticalSection",
    "AssetDisposal", "AssetRevaluation", "AuditLog",
    "Budget", "BudgetConsumption", "BudgetLine",
    "BankStatement", "BankStatementLine",
    "CashForecastWeek", "CashPositionSnapshot",
    "CashflowForecast", "CnpsDeclaration",
    "CreditNote", "CreditNoteLine", "Customer", "CustomerInvoice", "CustomerInvoiceLine",
    "CustomerPayment", "DeliveryNote", "DeliveryNoteLine", "DepreciationEntry",
    "DgiDeclaration", "Ecriture", "EcritureLigne", "Employee", "Exercice",
    "FifoLayer", "FinancialStatement", "FixedAsset",
    "FreezeCascadeRule", "FreezeEvent", "FreezeTarget",
    "GoodsReceipt", "GoodsReceiptLine",
    "Item", "ItemCategory", "Journal", "MmTransaction",
    "NlpFeedback", "NlpPattern", "NlpSuggestion", "Payslip", "Plan", "PlanComptable",
    "PurchaseOrder", "PurchaseOrderLine", "Quote", "QuoteLine",
    "ReconciliationSession",
    "SalesOrder", "SalesOrderLine", "Session",
    "StockInventory", "StockInventoryLine", "StockLevel", "StockMovement",
    "Subscription", "SubscriptionPayment",
    "Supplier", "SupplierInvoice", "SupplierInvoiceLine", "SupplierPayment",
    "Tenant", "TenantFreezeState", "TreasuryAccount",
    "User", "Warehouse", "WhatsAppLink", "WhatsAppMessage",
]
