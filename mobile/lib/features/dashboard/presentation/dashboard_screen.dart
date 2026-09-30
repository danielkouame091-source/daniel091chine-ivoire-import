import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_theme.dart';
import '../../../shared/widgets/kpi_card.dart';
import '../../../shared/widgets/section_header.dart';
import '../../../shared/utils/format.dart';
import '../providers/dashboard_provider.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncData = ref.watch(dashboardProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Tableau de bord'),
        actions: [
          IconButton(
            icon: const Icon(Icons.notifications_outlined),
            onPressed: () {},
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(dashboardProvider.future),
        child: asyncData.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => _ErrorView(message: e.toString(), onRetry: () => ref.refresh(dashboardProvider.future)),
          data: (data) => ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // KPIs grid 2x2
              GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
                childAspectRatio: 1.55,
                children: [
                  KpiCard(
                    label: 'Trésorerie',
                    value: Format.xof(data.summary.soldeTresorerie),
                    icon: Icons.account_balance_wallet_outlined,
                    color: AppColors.brand,
                  ),
                  KpiCard(
                    label: 'CA du mois',
                    value: Format.xof(data.summary.chiffreAffairesMois),
                    icon: Icons.trending_up,
                    color: AppColors.success,
                    variationPct: data.summary.variationCaPct,
                  ),
                  KpiCard(
                    label: 'Résultat net',
                    value: Format.xof(data.summary.resultatNet),
                    icon: Icons.pie_chart_outline,
                    color: AppColors.warning,
                  ),
                  KpiCard(
                    label: 'Créances clients',
                    value: Format.xof(data.summary.creancesClients),
                    icon: Icons.receipt_long_outlined,
                    color: const Color(0xFF8B5CF6),
                    badge: data.summary.facturesEnRetard > 0
                        ? '${data.summary.facturesEnRetard} en retard'
                        : null,
                    badgeColor: AppColors.danger,
                  ),
                ],
              ),

              const SizedBox(height: 24),
              const SectionHeader(title: 'Évolution du CA (12 mois)'),
              const SizedBox(height: 12),
              _CaChart(points: data.caMensuel),

              const SizedBox(height: 24),
              const SectionHeader(title: 'Trésorerie (12 mois)'),
              const SizedBox(height: 12),
              _TresorerieChart(points: data.tresorerie12Mois),
            ],
          ),
        ),
      ),
    );
  }
}

class _CaChart extends StatelessWidget {
  const _CaChart({required this.points});
  final List<dynamic> points;

  @override
  Widget build(BuildContext context) {
    if (points.isEmpty) return const SizedBox(height: 200);

    final maxY = points.map((p) => p.value as double).reduce((a, b) => a > b ? a : b);
    return SizedBox(
      height: 220,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 20, 20, 12),
          child: LineChart(
            LineChartData(
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                horizontalInterval: maxY / 4,
                getDrawingHorizontalLine: (_) => const FlLine(
                  color: AppColors.border,
                  strokeWidth: 1,
                ),
              ),
              titlesData: FlTitlesData(
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 46,
                    getTitlesWidget: (v, meta) => Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: Text(Format.xofCompact(v.toInt()),
                          style: const TextStyle(fontSize: 10, color: AppColors.textMuted)),
                    ),
                  ),
                ),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 28,
                    getTitlesWidget: (v, meta) {
                      final idx = v.toInt();
                      if (idx < 0 || idx >= points.length) return const SizedBox.shrink();
                      return Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text((points[idx].label as String).substring(5),
                            style: const TextStyle(fontSize: 10, color: AppColors.textMuted)),
                      );
                    },
                  ),
                ),
                rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              ),
              borderData: FlBorderData(show: false),
              lineBarsData: [
                LineChartBarData(
                  spots: List.generate(
                    points.length,
                    (i) => FlSpot(i.toDouble(), points[i].value as double),
                  ),
                  isCurved: true,
                  color: AppColors.brand,
                  barWidth: 3,
                  dotData: const FlDotData(show: false),
                  belowBarData: BarAreaData(
                    show: true,
                    color: AppColors.brand.withOpacity(0.08),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _TresorerieChart extends StatelessWidget {
  const _TresorerieChart({required this.points});
  final List<dynamic> points;

  @override
  Widget build(BuildContext context) {
    if (points.isEmpty) return const SizedBox(height: 200);

    return SizedBox(
      height: 220,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 20, 20, 12),
          child: LineChart(
            LineChartData(
              gridData: const FlGridData(show: false),
              titlesData: const FlTitlesData(show: false),
              borderData: FlBorderData(show: false),
              lineBarsData: [
                LineChartBarData(
                  spots: List.generate(
                    points.length,
                    (i) => FlSpot(i.toDouble(), points[i].value as double),
                  ),
                  isCurved: true,
                  color: AppColors.success,
                  barWidth: 3,
                  dotData: const FlDotData(show: false),
                  belowBarData: BarAreaData(
                    show: true,
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        AppColors.success.withOpacity(0.25),
                        AppColors.success.withOpacity(0.02),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.cloud_off, size: 64, color: AppColors.textMuted),
            const SizedBox(height: 16),
            const Text('Impossible de charger les données'),
            const SizedBox(height: 8),
            Text(message, style: const TextStyle(color: AppColors.textMuted, fontSize: 12), textAlign: TextAlign.center),
            const SizedBox(height: 24),
            ElevatedButton(onPressed: onRetry, child: const Text('Réessayer')),
          ],
        ),
      ),
    );
  }
}
