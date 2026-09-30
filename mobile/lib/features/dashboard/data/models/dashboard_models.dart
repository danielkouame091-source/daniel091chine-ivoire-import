import 'package:freezed_annotation/freezed_annotation.dart';

part 'dashboard_models.freezed.dart';
part 'dashboard_models.g.dart';

@freezed
class DashboardSummary with _$DashboardSummary {
  const factory DashboardSummary({
    required int soldeTresorerie,
    required int chiffreAffairesMois,
    required int resultatNet,
    required int creancesClients,
    required int dettesFournisseurs,
    required int facturesEnRetard,
    required int nbEcrituresMois,
    required double variationCaPct,
  }) = _DashboardSummary;

  factory DashboardSummary.fromJson(Map<String, dynamic> json) =>
      _$DashboardSummaryFromJson(json);
}

@freezed
class ChartPoint with _$ChartPoint {
  const factory ChartPoint({
    required String label,
    required double value,
  }) = _ChartPoint;

  factory ChartPoint.fromJson(Map<String, dynamic> json) =>
      _$ChartPointFromJson(json);
}

@freezed
class DashboardFull with _$DashboardFull {
  const factory DashboardFull({
    required DashboardSummary summary,
    required List<ChartPoint> caMensuel,
    required List<ChartPoint> tresorerie12Mois,
  }) = _DashboardFull;

  factory DashboardFull.fromJson(Map<String, dynamic> json) =>
      _$DashboardFullFromJson(json);
}
