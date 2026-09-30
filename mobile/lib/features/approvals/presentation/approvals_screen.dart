import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_theme.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/utils/format.dart';

class ApprovalItem {
  ApprovalItem({
    required this.id,
    required this.type,
    required this.titre,
    required this.details,
    required this.dateIso,
    required this.montantXof,
  });

  final String id;
  final String type;    // conge | depense | ecriture
  final String titre;
  final String details;
  final String dateIso;
  final int montantXof;
}

final approvalsProvider = FutureProvider.autoDispose<List<ApprovalItem>>((ref) async {
  final dio = ApiClient.dio;
  final response = await dio.get('/api/v1/hr/leave-requests', queryParameters: {
    'statut': 'soumise',
    'limit': 50,
  });

  final List data = response.data as List;
  return data.map<ApprovalItem>((e) => ApprovalItem(
    id: e['id'] as String,
    type: 'conge',
    titre: 'Demande de congé ${e['type_conge']}',
    details: 'Du ${Format.date(e['date_debut'])} au ${Format.date(e['date_fin'])} — ${e['nb_jours_ouvrables']} jours',
    dateIso: e['created_at'] as String,
    montantXof: 0,
  )).toList();
});

class ApprovalsScreen extends ConsumerWidget {
  const ApprovalsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncList = ref.watch(approvalsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('À approuver')),
      body: asyncList.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Erreur : $e')),
        data: (items) {
          if (items.isEmpty) {
            return const Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.check_circle_outline, size: 64, color: AppColors.success),
                  SizedBox(height: 12),
                  Text('Aucune demande en attente'),
                ],
              ),
            );
          }
          return RefreshIndicator(
            onRefresh: () => ref.refresh(approvalsProvider.future),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (_, i) => _ApprovalCard(item: items[i]),
            ),
          );
        },
      ),
    );
  }
}

class _ApprovalCard extends ConsumerWidget {
  const _ApprovalCard({required this.item});
  final ApprovalItem item;

  Future<void> _approve(WidgetRef ref, bool approve) async {
    final dio = ApiClient.dio;
    if (item.type == 'conge') {
      await dio.post(
        '/api/v1/hr/leave-requests/${item.id}/valider-manager',
        data: {
          'approuve': approve,
          'commentaire': approve ? 'Validé depuis mobile' : 'Refusé depuis mobile',
        },
      );
      ref.invalidate(approvalsProvider);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
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
            children: [
              const Icon(Icons.event_available, color: AppColors.brand, size: 20),
              const SizedBox(width: 8),
              Expanded(child: Text(item.titre, style: const TextStyle(fontWeight: FontWeight.w600))),
            ],
          ),
          const SizedBox(height: 8),
          Text(item.details, style: const TextStyle(color: AppColors.textMuted, fontSize: 13)),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _approve(ref, false),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.danger,
                    side: const BorderSide(color: AppColors.danger),
                  ),
                  child: const Text('Refuser'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton(
                  onPressed: () => _approve(ref, true),
                  child: const Text('Approuver'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
