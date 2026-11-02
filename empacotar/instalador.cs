// Instalar-Estante.exe: instala a Estante para quem não tem Python. Feito pelo empacotar.py com o compilador de C#
// que já vem no Windows. O programa (app) e o Python portátil (python) vêm dentro dele, no recurso "estante.zip".
// Instala só para quem está usando o computador, sem pedir senha de administrador:
//   %LOCALAPPDATA%\Programs\Estante\app e \python, atalhos na área de trabalho e no menu Iniciar,
//   e "Estante" em Configurações > Aplicativos, para desinstalar. Os dados ficam em %APPDATA%\Estante.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Sockets;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

class Instalador
{
    const string Titulo = "Estante";

    static bool EstanteAberta()
    {
        try
        {
            using (var c = new TcpClient())
            {
                var r = c.BeginConnect("127.0.0.1", 8765, null, null);
                return r.AsyncWaitHandle.WaitOne(500) && c.Connected;
            }
        }
        catch { return false; }
    }

    static void Atalhos(string pythonw, string estante, string app)
    {
        Type t = Type.GetTypeFromProgID("WScript.Shell");
        object sh = Activator.CreateInstance(t);
        foreach (var pasta in new[] { Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                                      Environment.GetFolderPath(Environment.SpecialFolder.Programs) })
        {
            object lnk = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, sh, new object[] { Path.Combine(pasta, "Estante.lnk") });
            Type lt = lnk.GetType();
            lt.InvokeMember("TargetPath", BindingFlags.SetProperty, null, lnk, new object[] { pythonw });
            lt.InvokeMember("Arguments", BindingFlags.SetProperty, null, lnk, new object[] { "\"" + estante + "\"" });
            lt.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, lnk, new object[] { app });
            lt.InvokeMember("IconLocation", BindingFlags.SetProperty, null, lnk, new object[] { Path.Combine(app, "estante.ico") });
            lt.InvokeMember("Description", BindingFlags.SetProperty, null, lnk, new object[] { "Estante" });
            lt.InvokeMember("Save", BindingFlags.InvokeMethod, null, lnk, null);
        }
    }

    static void RegistrarDesinstalar(string base_, string app)
    {
        string versao = File.Exists(Path.Combine(app, "VERSAO.txt")) ? File.ReadAllText(Path.Combine(app, "VERSAO.txt")).Trim() : "";
        using (var k = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\Estante"))
        {
            k.SetValue("DisplayName", "Estante");
            k.SetValue("DisplayVersion", versao);
            k.SetValue("Publisher", "vinimosi");
            k.SetValue("DisplayIcon", Path.Combine(app, "estante.ico"));
            k.SetValue("InstallLocation", base_);
            k.SetValue("UninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + Path.Combine(app, "desinstalar.ps1") + "\"");
            k.SetValue("NoModify", 1, RegistryValueKind.DWord);
            k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        }
    }

    [STAThread]
    static int Main()
    {
        string base_ = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Estante");
        if (EstanteAberta())
        {
            MessageBox.Show("A Estante está aberta. Feche ela antes (clique com o botão direito no ícone dela, perto do relógio, " +
                            "e em \"Fechar a Estante\") e abra o instalador de novo.", Titulo, MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
        bool jaTinha = Directory.Exists(Path.Combine(base_, "app"));
        var ok = MessageBox.Show((jaTinha ? "Atualizar a Estante deste computador?" : "Instalar a Estante neste computador?") +
            "\n\nO programa vai para " + base_ + " e ganha um atalho na área de trabalho e no menu Iniciar. " +
            "Seus jogos, séries e configurações ficam guardados à parte, em %APPDATA%\\Estante, e não se perdem.",
            "Instalar a Estante", MessageBoxButtons.OKCancel, MessageBoxIcon.Question);
        if (ok != DialogResult.OK) return 0;
        string nova = Path.Combine(base_, "instalando");
        try
        {
            Directory.CreateDirectory(base_);
            if (Directory.Exists(nova)) Directory.Delete(nova, true);
            using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("estante.zip"))
            using (var z = new ZipArchive(s))
                z.ExtractToDirectory(nova);
            foreach (var parte in new[] { "app", "python" })
            {
                string atual = Path.Combine(base_, parte), velha = Path.Combine(base_, parte + "-anterior");
                if (Directory.Exists(velha)) Directory.Delete(velha, true);
                if (Directory.Exists(atual)) Directory.Move(atual, velha);
                Directory.Move(Path.Combine(nova, parte), atual);
            }
            Directory.Delete(nova, true);
            string app = Path.Combine(base_, "app"), pythonw = Path.Combine(base_, "python", "pythonw.exe"), estante = Path.Combine(app, "Estante.pyw");
            Atalhos(pythonw, estante, app);
            RegistrarDesinstalar(base_, app);
            Process.Start(new ProcessStartInfo(pythonw, "\"" + estante + "\"") { WorkingDirectory = app, UseShellExecute = false });
            MessageBox.Show("Pronto! A Estante foi " + (jaTinha ? "atualizada" : "instalada") + " e já está abrindo.\n\n" +
                "Para a Estante marcar sozinha o que você lê nos sites, instale a extensão do navegador: na Estante, " +
                "abra a Leitura e use Adicionar > Instalar a extensão.", Titulo, MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 0;
        }
        catch (Exception e)
        {
            // se trocou só uma parte, volta a anterior
            foreach (var parte in new[] { "app", "python" })
            {
                string atual = Path.Combine(base_, parte), velha = Path.Combine(base_, parte + "-anterior");
                try { if (!Directory.Exists(atual) && Directory.Exists(velha)) Directory.Move(velha, atual); } catch { }
            }
            MessageBox.Show("Não deu para instalar: " + e.Message, Titulo, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
