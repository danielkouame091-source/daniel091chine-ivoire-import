import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hive_flutter/hive_flutter.dart';

import '../../../core/network/api_client.dart';
import '../../../core/storage/hive_boxes.dart';
import '../data/dashboard_repository.dart';
import '../data/models/dashboard_models.dart';

final dashboardRepositoryProvider = Provider<DashboardRepository>(
  (ref) => DashboardRepository(ApiClient.dio),
);

final dashboardProvider = FutureProvider<DashboardFull>((ref) async {
  final repo = ref.watch(dashboardRepositoryProvider);
  try {
    final data = await repo.fetch();
    // Cache offline
    await HiveBoxes.getDashboard().put('last_summary', data.toJson());
    return data;
  } catch (_) {
    // Fallback sur le cache
    final cached = HiveBoxes.getDashboard().get('last_summary');
    if (cached != null && cached is Map) {
      return DashboardFull.fromJson(Map<String, dynamic>.from(cached));
    }
    rethrow;
  }
});
