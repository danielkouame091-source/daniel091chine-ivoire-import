import 'package:dio/dio.dart';

import 'models/dashboard_models.dart';

class DashboardRepository {
  DashboardRepository(this._dio);
  final Dio _dio;

  Future<DashboardFull> fetch() async {
    final response = await _dio.get('/api/v1/bi/dashboard/dirigeant');
    return DashboardFull.fromJson(response.data);
  }

  Future<List<ChartPoint>> fetchCaSerie({int mois = 12}) async {
    final response = await _dio.get(
      '/api/v1/bi/kpis/CA_MENSUEL/serie',
      queryParameters: {
        'date_debut': DateTime.now().subtract(Duration(days: 30 * mois)).toIso8601String().substring(0, 10),
        'date_fin':   DateTime.now().toIso8601String().substring(0, 10),
        'granularite': 'month',
      },
    );
    final List data = response.data as List;
    return data
        .map((e) => ChartPoint(label: e['date'] as String, value: (e['valeur'] as num).toDouble()))
        .toList();
  }
}
