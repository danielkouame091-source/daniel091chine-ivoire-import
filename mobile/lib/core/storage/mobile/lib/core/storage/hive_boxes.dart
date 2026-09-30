import 'package:hive_flutter/hive_flutter.dart';

class HiveBoxes {
  static const invoices   = 'invoices';
  static const dashboard  = 'dashboard';
  static const approvals  = 'approvals';
  static const scanQueue  = 'scan_queue';
  static const settings   = 'settings';

  static Future<void> open() async {
    await Hive.openBox(invoices);
    await Hive.openBox(dashboard);
    await Hive.openBox(approvals);
    await Hive.openBox(scanQueue);
    await Hive.openBox(settings);
  }

  static Box getInvoices()  => Hive.box(invoices);
  static Box getDashboard() => Hive.box(dashboard);
  static Box getApprovals() => Hive.box(approvals);
  static Box getScanQueue() => Hive.box(scanQueue);
  static Box getSettings()  => Hive.box(settings);

  static Future<void> clearAll() async {
    await getInvoices().clear();
    await getDashboard().clear();
    await getApprovals().clear();
    await getScanQueue().clear();
    // Ne pas vider les settings (préférences UI)
  }
}
