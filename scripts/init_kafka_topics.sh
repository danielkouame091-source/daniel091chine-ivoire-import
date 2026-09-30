#!/usr/bin/env bash
# =============================================================================
# Création des topics Kafka — à exécuter UNE SEULE FOIS au déploiement.
# =============================================================================
set -euo pipefail

BROKER="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"

create_topic() {
  local topic=$1
  local partitions=$2
  local replication=${3:-3}

  kafka-topics.sh --bootstrap-server "$BROKER" \
    --create --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor "$replication" \
    --config retention.ms=604800000 \
    --config compression.type=gzip
}

# Comptabilité
create_topic "mtech.comptabilite.ecriture.created"   12
create_topic "mtech.comptabilite.ecriture.validated" 12

# Ventes
create_topic "mtech.ventes.invoice.created"          12
create_topic "mtech.ventes.invoice.paid"             12
create_topic "mtech.ventes.payment.received"         12

# Achats
create_topic "mtech.achats.purchase_order.created"   6
create_topic "mtech.achats.supplier_invoice.created" 6

# Trésorerie
create_topic "mtech.tresorerie.mobile_money.transaction" 24
create_topic "mtech.tresorerie.bank.transaction"     12
create_topic "mtech.tresorerie.reconciliation.done"  6

# Stocks
create_topic "mtech.stocks.movement"                 12
create_topic "mtech.stocks.low"                      6

# RH
create_topic "mtech.rh.leave.requested"              3
create_topic "mtech.rh.payslip.generated"            6

# FNE
create_topic "mtech.fne.certified"                   12
create_topic "mtech.fne.rejected"                    6

# Projets
create_topic "mtech.projets.milestone.reached"       6

# Audit
create_topic "mtech.audit.finding.detected"          6

echo "✅ Tous les topics Kafka sont créés."
