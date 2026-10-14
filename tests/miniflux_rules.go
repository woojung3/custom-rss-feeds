// Offline compatibility check for Miniflux 2.3.3's text/scanner ->
// strconv.Unquote -> regexp pipeline. No network or Miniflux requests.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"text/scanner"
)

type rule struct {
	name string
	args []string
}

func check(err error) {
	if err != nil {
		panic(err)
	}
}

func parse(text string) []rule {
	var scan scanner.Scanner
	scan.Init(strings.NewReader(text))
	scan.Mode = scanner.ScanIdents | scanner.ScanStrings
	scan.Error = func(_ *scanner.Scanner, message string) { panic(message) }
	var rules []rule
	for token := scan.Scan(); token != scanner.EOF; token = scan.Scan() {
		switch token {
		case scanner.Ident:
			if scan.TokenText() != "replace" {
				panic("unexpected rule")
			}
			rules = append(rules, rule{name: "replace"})
		case scanner.String:
			if len(rules) == 0 {
				panic("argument without rule")
			}
			value, err := strconv.Unquote(scan.TokenText())
			check(err)
			i := len(rules) - 1
			rules[i].args = append(rules[i].args, value)
		}
	}
	if len(rules) != 4 {
		panic("expected four narrow rules")
	}
	for _, rule := range rules {
		if len(rule.args) != 2 || rule.args[0] == "" {
			panic("invalid/empty pattern")
		}
		pattern, err := regexp.Compile(rule.args[0])
		check(err)
		if pattern.MatchString("") {
			panic("pattern matches empty string")
		}
	}
	return rules
}

func main() {
	if len(os.Args) != 2 {
		panic("usage: validator recipe.json")
	}
	data, err := os.ReadFile(os.Args[1])
	check(err)
	var config map[string]string
	check(json.Unmarshal(data, &config))
	rules := parse(config["rewrite_rules"])
	for _, bad := range []string{`replace("\s"|"x")`, strings.TrimSuffix(strings.Repeat(`replace(""|"x"),`, 4), ",")} {
		rejected := func() (rejected bool) {
			defer func() {
				if recover() != nil {
					rejected = true
				}
			}()
			parse(bad)
			return false
		}()
		if !rejected {
			panic("unsafe rule was accepted")
		}
	}
	apply := func(input string) string {
		for _, rule := range rules {
			pattern, err := regexp.Compile(rule.args[0])
			check(err)
			input = pattern.ReplaceAllString(input, rule.args[1])
			if len(input) > 100000 {
				panic("unexpected output growth")
			}
		}
		return input
	}
	for _, host := range []string{"dcimg6.dcinside.co.kr", "dcimg5.dcinside.com"} {
		for _, route := range []string{"viewimage.php", "dccon.php"} {
			url := "https://" + host + "/" + route + "?id=x&amp;no=1"
			input := `<p>` + url + `</p><a href="` + url + `">link</a><img alt="test" src="` + url + `"/>`
			want := `<p>` + url + `</p><a href="` + url + `">link</a><img alt="test" src="https://image.dcinside.com/` + route + `?id=x&amp;no=1"/>`
			if got := apply(input); got != want || apply(got) != got {
				panic("rewrite mismatch")
			}
		}
	}
	fmt.Println("Go decoding, invalid-escape/empty-pattern rejection, four image routes, unrelated links and idempotence: PASS")
}
