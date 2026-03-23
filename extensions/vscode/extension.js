const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

function activate(context) {
  const provider = new FixTapeSessionsProvider();
  const treeView = vscode.window.createTreeView("fixtapeSessions", { treeDataProvider: provider });
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);

  const refreshStatusBar = async () => {
    const sessions = provider.loadSessions();
    const active = sessions.find((item) => item.isActive);
    if (active) {
      statusBar.text = `$(debug-alt-small) FixTape: ${active.session.title}`;
      statusBar.tooltip = `Active FixTape session: ${active.session.title}`;
      statusBar.command = {
        command: "fixtape.openBestEntry",
        title: "Open FixTape Session",
        arguments: [active]
      };
      statusBar.show();
      return;
    }
    if (sessions.length > 0) {
      statusBar.text = "$(history) FixTape";
      statusBar.tooltip = "Open the most recent FixTape session";
      statusBar.command = {
        command: "fixtape.openBestEntry",
        title: "Open FixTape Session",
        arguments: [sessions[0]]
      };
      statusBar.show();
      return;
    }
    statusBar.hide();
  };

  const refreshAll = () => {
    provider.refresh();
    refreshStatusBar();
  };

  const openDocumentIfExists = async (targetPath) => {
    if (!targetPath || !fs.existsSync(targetPath)) {
      vscode.window.showWarningMessage("FixTape file not found for this session.");
      return;
    }
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(targetPath));
    await vscode.window.showTextDocument(document, { preview: false });
  };

  const resolveSessionItem = (sessionItem) => {
    if (sessionItem) {
      return sessionItem;
    }
    const sessions = provider.loadSessions();
    return sessions[0];
  };

  context.subscriptions.push(
    treeView,
    statusBar,
    vscode.commands.registerCommand("fixtape.refreshSessions", refreshAll),
    vscode.commands.registerCommand("fixtape.openSummary", async (sessionItem) => {
      const item = resolveSessionItem(sessionItem);
      if (!item) {
        vscode.window.showInformationMessage("No FixTape sessions found in the current workspace.");
        return;
      }
      await openDocumentIfExists(item.summaryPath);
    }),
    vscode.commands.registerCommand("fixtape.openHandoff", async (sessionItem) => {
      const item = resolveSessionItem(sessionItem);
      if (!item) {
        vscode.window.showInformationMessage("No FixTape sessions found in the current workspace.");
        return;
      }
      await openDocumentIfExists(item.handoffPath);
    }),
    vscode.commands.registerCommand("fixtape.openBestEntry", async (sessionItem) => {
      const item = resolveSessionItem(sessionItem);
      if (!item) {
        vscode.window.showInformationMessage("No FixTape sessions found in the current workspace.");
        return;
      }
      if (item.handoffPath && fs.existsSync(item.handoffPath)) {
        await openDocumentIfExists(item.handoffPath);
        return;
      }
      await openDocumentIfExists(item.summaryPath);
    }),
    vscode.commands.registerCommand("fixtape.revealSession", async (sessionItem) => {
      const item = resolveSessionItem(sessionItem);
      if (!item) {
        vscode.window.showInformationMessage("No FixTape sessions found in the current workspace.");
        return;
      }
      await vscode.commands.executeCommand("revealFileInOS", vscode.Uri.file(item.sessionDir));
    })
  );

  const watchers = [];
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const pattern = new vscode.RelativePattern(folder, ".fixtape/**");
    const watcher = vscode.workspace.createFileSystemWatcher(pattern);
    watcher.onDidCreate(refreshAll);
    watcher.onDidChange(refreshAll);
    watcher.onDidDelete(refreshAll);
    watchers.push(watcher);
  }
  context.subscriptions.push(...watchers);

  refreshAll();
}

class FixTapeSessionsProvider {
  constructor() {
    this._onDidChangeTreeData = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._onDidChangeTreeData.event;
  }

  refresh() {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element) {
    return element;
  }

  getChildren(element) {
    if (element) {
      return [];
    }
    return this.loadSessions();
  }

  loadSessions() {
    const folders = vscode.workspace.workspaceFolders || [];
    const items = [];
    for (const folder of folders) {
      const storeRoot = path.join(folder.uri.fsPath, ".fixtape");
      const sessionsRoot = path.join(storeRoot, "sessions");
      if (!fs.existsSync(sessionsRoot)) {
        continue;
      }

      const activePointer = readJson(path.join(storeRoot, "active-session.json"));
      const activeSessionId = activePointer && activePointer.session_id ? activePointer.session_id : null;

      const sessionDirs = fs
        .readdirSync(sessionsRoot, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => path.join(sessionsRoot, entry.name));

      for (const sessionDir of sessionDirs) {
        const sessionPath = path.join(sessionDir, "session.json");
        const session = readJson(sessionPath);
        if (!session) {
          continue;
        }
        items.push(
          createSessionTreeItem({
            workspaceFolder: folder.name,
            sessionDir,
            session,
            isActive: session.id === activeSessionId
          })
        );
      }
    }

    items.sort((a, b) => {
      if (a.isActive && !b.isActive) {
        return -1;
      }
      if (!a.isActive && b.isActive) {
        return 1;
      }
      return String(b.session.created_at || "").localeCompare(String(a.session.created_at || ""));
    });
    return items;
  }
}

function createSessionTreeItem({ workspaceFolder, sessionDir, session, isActive }) {
  const generatedDir = path.join(sessionDir, "generated");
  const summaryPath = path.join(generatedDir, "debug-summary.md");
  const handoffPath = path.join(generatedDir, "handoff.md");
  const verdict = session.verdict || (isActive ? "active" : "n/a");
  const refs = Array.isArray(session.refs) ? session.refs : [];

  const item = new vscode.TreeItem(
    session.title,
    vscode.TreeItemCollapsibleState.None
  );
  item.contextValue = "fixtapeSession";
  item.description = `${verdict} · ${workspaceFolder}`;
  item.tooltip = [
    `Session ID: ${session.id}`,
    `Created: ${session.created_at || "n/a"}`,
    `Verdict: ${verdict}`,
    refs.length ? `Refs: ${refs.join(", ")}` : null,
    `Directory: ${sessionDir}`
  ]
    .filter(Boolean)
    .join("\n");
  item.iconPath = isActive
    ? new vscode.ThemeIcon("debug-alt-small")
    : new vscode.ThemeIcon(session.verdict === "fixed" ? "pass-filled" : "history");
  item.command = {
    command: "fixtape.openBestEntry",
    title: "Open FixTape Session",
    arguments: [Object.assign(item, { sessionDir, session, isActive, summaryPath, handoffPath })]
  };

  item.sessionDir = sessionDir;
  item.session = session;
  item.isActive = isActive;
  item.summaryPath = summaryPath;
  item.handoffPath = handoffPath;
  return item;
}

function readJson(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
};
