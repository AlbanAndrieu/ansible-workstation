// import config from "commitlint-config-gitmoji";
import config from "@commitlint/config-conventional";
import type { ParserPreset, UserConfig } from "@commitlint/types";
import createPreset from "conventional-changelog-conventionalcommits";
import { merge } from "lodash-es";

// A helper function to create the custom emoji parser preset.
async function createEmojiParser(): Promise<ParserPreset> {
	// Generates the regex from the emojis defined in the conventional config.
	const emojiRegexPart = Object.values(config.prompt.questions.type.enum)
		.map((value) => value.emoji.trim())
		.join("|");

	const parserOpts = {
		// This regular expression validates commit headers with an emoji.
		breakingHeaderPattern: new RegExp(
			`^(?:${emojiRegexPart})\\s+(\\w*)(?:\\((.*)\\))?!:\\s+(.*)$`,
		),
		headerPattern: new RegExp(
			`^(?:${emojiRegexPart})\\s+(\\w*)(?:\\((.*)\\))?!?:\\s+(.*)$`,
		),
	};

	const emojiParser = merge({}, await createPreset(), {
		conventionalChangelog: { parserOpts },
		parserOpts,
		recommendedBumpOpts: { parserOpts },
	});

	return emojiParser;
}

const emojiParser = await createEmojiParser();

export default {
	extends: ["@commitlint/config-conventional"],
	//extends: ["./node_modules/commitlint-config-gitmoji", "@commitlint/config-conventional"],
	parserPreset: {
		emojiParser,
		parserOpts: {
			// these are samples, add possible prefixes based on your project requirement
			issuePrefixes: ["ANDR-", "TEST-", "DSC-", "NABLA-", "AA-"],
		},
	},
	rules: {
		//  Wrap the body at 100 characters.
		"body-max-line-length": [2, "always", 100],
		//  Body is added by leaving a blank line after the subject line.
		"body-leading-blank": [1, "always"],
		// Ensure a blank line precedes the footer.
		"footer-leading-blank": [1, "always"],
		// Subject/Description Rules:
		// Short and Summarized: Try to fit the subject line inside 72 characters (80 with emoji).
		"header-max-length": [2, "always", 80],
		// Enforce that if a scope is used, it is in lower-case.
		"scope-case": [2, "always", "lower-case"],
		// Capitalize the description: Start subject line with a capital letter.
		// 'sentence-case' helps with generating changelogs.
		"subject-case": [
			2,
			"never",
			["sentence-case", "start-case", "pascal-case", "upper-case"],
		],
		"subject-empty": [2, "never"],
		// Avoid trailing period.
		"subject-full-stop": [2, "never", "."],
		"type-case": [2, "always", "lower-case"],
		// Format: <type>([optional scope]): <description> - enforced by most rules below.
		// Enforce that the type is not empty.
		"type-empty": [2, "never"],
		// Enforce specific commit types. Add/remove types based on the project.
		"type-enum": [
			2,
			"always",
			[
				"build",
				"chore",
				"ci",
				"docs",
				"feat",
				"feature",
				"fix",
				"perf",
				"refactor",
				"revert",
				"style",
				"test",
			],
		],
		// "references-empty": [2, "never"],
	},
	prompt: {
		settings: {},
		messages: {
			skip: ":skip",
			max: "upper %d chars",
			min: "%d chars at least",
			emptyWarning: "can not be empty",
			upperLimitWarning: "over limit",
			lowerLimitWarning: "below limit",
		},
		questions: {
			type: {
				description: "Select the type of change that you're committing:",
				enum: {
					feat: {
						description: "A new feature",
						title: "Features",
						emoji: "✨",
					},
					fix: {
						description: "A bug fix",
						title: "Bug Fixes",
						emoji: "🐛",
					},
					docs: {
						description: "Documentation only changes",
						title: "Documentation",
						emoji: "📚",
					},
					style: {
						description:
							"Changes that do not affect the meaning of the code (white-space, formatting, missing semi-colons, etc)",
						title: "Styles",
						emoji: "💎",
					},
					refactor: {
						description:
							"A code change that neither fixes a bug nor adds a feature",
						title: "Code Refactoring",
						emoji: "📦",
					},
					perf: {
						description: "A code change that improves performance",
						title: "Performance Improvements",
						emoji: "🚀",
					},
					test: {
						description: "Adding missing tests or correcting existing tests",
						title: "Tests",
						emoji: "🚨",
					},
					build: {
						description:
							"Changes that affect the build system or external dependencies (example scopes: gulp, broccoli, npm)",
						title: "Builds",
						emoji: "🛠️",
					},
					ci: {
						description:
							"Changes to our CI configuration files and scripts (example scopes: Travis, Circle, BrowserStack, SauceLabs)",
						title: "Continuous Integrations",
						emoji: "⚙️",
					},
					chore: {
						description: "Other changes that don't modify src or test files",
						title: "Chores",
						emoji: "♻️",
					},
					revert: {
						description: "Reverts a previous commit",
						title: "Reverts",
						emoji: "🗑️",
					},
				},
				// This setting includes the emoji in the final commit header.
				headerWithEmoji: true,
			},
			scope: {
				description:
					"What is the scope of this change (e.g. component or file name)",
			},
			subject: {
				description:
					"Write a short, imperative tense description of the change",
			},
			body: {
				description: "Provide a longer description of the change",
			},
			isBreaking: {
				description: "Are there any breaking changes?",
			},
			breakingBody: {
				description:
					"A BREAKING CHANGE commit requires a body. Please enter a longer description of the commit itself",
			},
			breaking: {
				description: "Describe the breaking changes",
			},
			isIssueAffected: {
				description: "Does this change affect any open issues?",
			},
			issuesBody: {
				description:
					"If issues are closed, the commit requires a body. Please enter a longer description of the commit itself",
			},
			issues: {
				description: 'Add issue references (e.g. "fix #123", "re #123".)',
			},
		},
	},
} satisfies UserConfig;
