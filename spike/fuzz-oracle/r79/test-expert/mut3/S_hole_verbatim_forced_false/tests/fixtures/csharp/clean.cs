using System;

namespace Widgets
{
    /// <summary>Represents a widget and its literal-form exercises.</summary>
    public class Widget
    {
        // A regular escaped string: the quote here is escaped, not real.
        private string Url = "http://example.com/\"quoted\"/path";

        // A verbatim string: backslashes and // are just text here.
        private string Path = @"C:\temp\not // a comment\""quoted""";

        // An interpolated string with a hole.
        private string Greeting = $"Hello, {Name}!";

        // A verbatim interpolated string, both prefix orders.
        private string A = $@"line one \ line two {Name}";
        private string B = @$"line one \ line two {Name}";

        // A raw string literal spanning multiple lines.
        private string Raw = """
            first line with /* not a comment */ inside
            second line with /// not a doc comment inside
            """;

        // A char literal holding an escaped single quote.
        private char Quote = '\'';

        // A char literal holding a double quote.
        private char DoubleQuote = '"';

        public string Name { get; set; }

        /* A short block comment naming what this does, nothing more. */
        public string Describe()
        {
            return $"{Name}: {Url}";
        }
    }
}
