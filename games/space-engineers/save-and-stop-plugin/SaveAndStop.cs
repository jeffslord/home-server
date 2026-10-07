// Space Engineers dedicated server plugin: save the world, then exit cleanly,
// when games/launcher asks. SE runs under Wine here, so `docker stop` can't
// reach it (it gets SIGKILLed) and the VRage Remote API doesn't work
// (Wine's http.sys). With PauseGameWhenEmpty, autosave doesn't run while
// empty either, so this is the only way to get a save right before stopping.
//
// Protocol, via <instance>/launcher/ (mounted read-write into the launcher):
//   launcher writes  save-and-stop
//   plugin deletes it, saves, writes  status  = "saved" or "save-failed", exits
//
// Build: ./build.sh (writes the DLL into the image's plugins dir).
using System;
using System.IO;
using Sandbox;
using Sandbox.Game.World;
using VRage.FileSystem;
using VRage.Plugins;
using VRage.Utils;

namespace HomeServer
{
    public class SaveAndStop : IPlugin
    {
        private string _dir;
        private int _tick;
        private bool _exiting;

        public void Init(object gameInstance)
        {
            _dir = Path.Combine(MyFileSystem.UserDataPath, "launcher");
            Directory.CreateDirectory(_dir);
            MyLog.Default.WriteLineAndConsole("SaveAndStop: watching " + _dir);
        }

        public void Update()
        {
            // Runs every tick (60/s), even while paused for being empty.
            if (_exiting || ++_tick % 60 != 0)
                return;
            string request = Path.Combine(_dir, "save-and-stop");
            if (!File.Exists(request) || MySession.Static == null || !MySession.Static.Ready)
                return;

            _exiting = true;
            File.Delete(request);
            MyLog.Default.WriteLineAndConsole("SaveAndStop: saving before shutdown");
            bool saved;
            try
            {
                saved = MySession.Static.Save();
            }
            catch (Exception e)
            {
                MyLog.Default.WriteLineAndConsole("SaveAndStop: save threw " + e);
                saved = false;
            }
            File.WriteAllText(Path.Combine(_dir, "status"), saved ? "saved" : "save-failed");
            MyLog.Default.WriteLineAndConsole("SaveAndStop: " + (saved ? "saved" : "save FAILED") + ", exiting");
            MySandboxGame.ExitThreadSafe();
        }

        public void Dispose()
        {
        }
    }
}
