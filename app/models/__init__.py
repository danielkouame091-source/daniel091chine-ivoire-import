"""Point d'entrée unique des modèles SQLAlchemy."""
from app.models.analytical import (
    AllocationKey, AllocationKeyLine, AnalyticalAxis, AnalyticalEntry,
    AnalyticalSection, Budget, BudgetConsumption, BudgetLine,
)
from app.models.asset import AssetDisposal, AssetRevaluation, DepreciationEntry, FixedAsset
from app.models.audit import AuditLog
from app.models.consolidation import (
    AdjustmentEntry, ConsolidationGroup, ConsolidationRun,
    EliminationEntry, ExchangeRate, GroupCompany,
    IntercompanyTransaction, MinorityInterest,
)
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.exercice import Exercice
from app.models.fne import (
    FneApiLog, FneConfiguration, FneEvent, FneInvoice, FneStickerBalance,
)
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
    "CashForecastWeek", "CashPositionSnapshot", "CashflowForecast",
    "CnpsDeclaration",
    "AdjustmentEntry", "ConsolidationGroup", "ConsolidationRun",
    "EliminationEntry", "ExchangeRate", "GroupCompany",
    "IntercompanyTransaction", "MinorityInterest",
    "CreditNote", "CreditNoteLine", "Customer", "CustomerInvoice", "CustomerInvoiceLine",
    "CustomerPayment", "DeliveryNote", "DeliveryNoteLine",
    "DepreciationEntry", "DgiDeclaration",
    "Ecriture", "EcritureLigne", "Employee", "Exercice",
    "FifoLayer", "FinancialStatement", "FixedAsset",
    "FneApiLog", "FneConfiguration", "FneEvent", "FneInvoice", "FneStickerBalance",
    "FreezeCascadeRule", "FreezeEvent", "FreezeTarget",
    "GoodsReceipt", "GoodsReceiptLine",
    "Item", "ItemCategory", "Journal", "MmTransaction",
    "NlpFeedback", "NlpPattern", "NlpSuggestion",
    "Payslip", "Plan", "PlanComptable",
    "PurchaseOrder", "PurchaseOrderLine",
    "Quote", "QuoteLine",
    "ReconciliationSession",
    "SalesOrder", "SalesOrderLine", "Session",
    "StockInventory", "StockInventoryLine", "StockLevel", "StockMovement",
    "Subscription", "SubscriptionPayment",
    "Supplier", "SupplierInvoice", "SupplierInvoiceLine", "SupplierPayment",
    "Tenant", "TenantFreezeState", "TreasuryAccount",
    "User", "Warehouse", "WhatsAppLink", "WhatsAppMessage",
]
from app.models.audit_internal import (
    AuditFinding, AuditRule, AuditRun, AuditTrail,
    BenfordAnalysis, ComplianceReport,
)

# Ajouter dans __all__ :
"AUDIT_FINDING", "AUDIT_RULE", "AUDIT_RUN", "AUDIT_TRAIL",
"BENFORD_ANALYSIS", "COMPLIANCE_REPORT",
from app.models.project import (
    ProgressBilling, ProgressBillingLine, Project, ProjectCost,
    ProjectMilestone, ProjectPhase, ProjectResourceAssignment, ProjectTask,
)

# Dans __all__ :
"ProgressBilling", "ProgressBillingLine", "Project", "ProjectCost",
"ProjectMilestone", "ProjectPhase", "ProjectResourceAssignment", "ProjectTask",
from app.models.formation import (
    Article, ArticleCategory, ChatbotConversation, ChatbotMessage,
    OnboardingPath, SupportTicket, TicketMessage, TutorialStep,
    UserArticleProgress, UserOnboardingProgress,
)

# Dans __all__ :
"Article", "ArticleCategory", "ChatbotConversation", "ChatbotMessage",
"OnboardingPath", "SupportTicket", "TicketMessage", "TutorialStep",
"UserArticleProgress", "UserOnboardingProgress",
from app.models.portal import (
    OnlinePayment, PortalConversation, PortalInvitation, PortalMessage,
    PortalNotification, PortalSession, PortalUser, SharedDocument,
    SupplierInvoiceSubmission,
)

# Dans __all__ :
"OnlinePayment", "PortalConversation", "PortalInvitation", "PortalMessage",
"PortalNotification", "PortalSession", "PortalUser", "SharedDocument",
"SupplierInvoiceSubmission",
from app.models.hr import (
    Department, DisciplinaryAction, EmployeeAbsence, EmployeeDocument,
    EmployeeOffboarding, EmploymentContract, LeaveBalance, LeaveRequest,
    PerformanceReview, TimeEntry, Training, TrainingParticipant,
)

# Dans __all__ :
"Department", "DisciplinaryAction", "EmployeeAbsence", "EmployeeDocument",
"EmployeeOffboarding", "EmploymentContract", "LeaveBalance", "LeaveRequest",
"PerformanceReview", "TimeEntry", "Training", "TrainingParticipant",
from app.models.notification import (
    Notification, NotificationCampaign, NotificationEvent,
    NotificationPreference, NotificationSuppression, NotificationTemplate,
    PushDevice,
)

# Dans __all__ :
"Notification", "NotificationCampaign", "NotificationEvent",
"NotificationPreference", "NotificationSuppression", "NotificationTemplate",
"PushDevice",
