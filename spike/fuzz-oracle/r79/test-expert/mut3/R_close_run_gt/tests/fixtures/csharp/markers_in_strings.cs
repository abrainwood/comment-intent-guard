using System;

namespace Widgets
{
    public class Widget
    {
        private string RegularNote = "see #99 for context";
        private string VerbatimNote = @"fixed on 2026-01-05";
        private string RawNote = """
            /// see #7 in the raw block
            """;

        public string Describe()
        {
            return RegularNote + VerbatimNote + RawNote;
        }
    }
}
