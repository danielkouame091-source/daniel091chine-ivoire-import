import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/config/app_theme.dart';
import '../../../shared/utils/format.dart';
import '../data/models/invoice.dart';
import '../providers/invoices_provider.dart';

class InvoicesListScreen extends ConsumerWidget {
  const InvoicesListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncList = ref.watch(invoicesListProvider);
    final filter    = ref.watch(invoicesFilterProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Factures')),
      body: Column(
        children: [
          // Filtres
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(
              children: InvoiceFilter.values.map((f) {
                final active = f == filter;
                return Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(_filterLabel(f)),
                    selected: active,
                    onSelected: (_) => ref.read(invoicesFilterProvider.notifier).state = f,
                    selectedColor: AppColors.brand,
                    labelStyle: TextStyle(color: active ? Colors.white : AppColors.textPrimary),
                  ),
                );
              }).toList(),
            ),
          ),

          Expanded(
            child: asyncList.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('Erreur : $e')),
              data: (invoices) {
                final filtered = _applyFilter(invoices, filter);
                if (filtered.isEmpty) {
                  return const Center(child: Text('Aucune facture'));
                }
                return RefreshIndicator(
                  onRefresh: () => ref.refresh(invoicesListProvider.future),
                  child: ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: filtered.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (_, i) => _InvoiceCard(invoice: filtered[i]),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  List<Invoice> _applyFilter(List<Invoice> list, InvoiceFilter filter) => switch (filter) {
        InvoiceFilter.all      => list,
        InvoiceFilter.unpaid   => list.where((i) => i.soldeDu > 0).toList(),
        InvoiceFilter.overdue  => list.where((i) => i.joursRetard > 0).toList(),
        InvoiceFilter.paid     => list.where((i) => i.soldeDu == 0).toList(),
      };

  String _filterLabel(InvoiceFilter f) => switch (f) {
        InvoiceFilter.all     => 'Toutes',
        InvoiceFilter.unpaid  => 'Impayées',
        InvoiceFilter.overdue => 'En retard',
        InvoiceFilter.paid    => 'Payées',
      };
}

class _InvoiceCard extends StatelessWidget {
  const _InvoiceCard({required this.invoice});
  final Invoice invoice;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => context.go('/invoices/${invoice.id}'),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(invoice.numero,
                    style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.w600)),
                _StatusBadge(statut: invoice.statut, joursRetard: invoice.joursRetard),
              ],
            ),
            const SizedBox(height: 8),
            if (invoice.clientNom != null)
              Text(invoice.clientNom!, style: const TextStyle(color: AppColors.textMuted, fontSize: 13)),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Échéance ${Format.date(invoice.dateEcheance)}',
                    style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
                Text(Format.xof(invoice.totalTtc),
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              ],
            ),
            if (invoice.soldeDu > 0) ...[
              const SizedBox(height: 6),
              Text('Reste dû : ${Format.xof(invoice.soldeDu)}',
                  style: const TextStyle(color: AppColors.danger, fontSize: 12, fontWeight: FontWeight.w500)),
            ],
          ],
        ),
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.statut, required this.joursRetard});
  final String statut;
  final int joursRetard;

  @override
  Widget build(BuildContext context) {
    late Color bg;
    late Color fg;
    late String label;

    if (joursRetard > 0) {
      bg = AppColors.danger.withOpacity(0.1);
      fg = AppColors.danger;
      label = 'En retard ($joursRetard j)';
    } else if (statut == 'payee' || statut == 'paye') {
      bg = AppColors.success.withOpacity(0.1);
      fg = AppColors.success;
      label = 'Payée';
    } else if (statut == 'partiellement_payee') {
      bg = AppColors.warning.withOpacity(0.1);
      fg = AppColors.warning;
      label = 'Partielle';
    } else {
      bg = AppColors.brand.withOpacity(0.1);
      fg = AppColors.brand;
      label = 'En attente';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(20)),
      child: Text(label, style: TextStyle(color: fg, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}
