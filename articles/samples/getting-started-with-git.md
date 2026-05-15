# Getting Started with Git: A Beginner-Friendly Guide to Version Control

Git is a tool that helps you track changes in your code. If you have ever saved files as `project-final`, `project-final-v2`, and `project-final-real-final`, you already understand the problem Git solves. Git gives you a cleaner way to save checkpoints, compare changes, and go back when something breaks.

Think of Git like a notebook for your project. Every time you reach a useful point, you can write down what changed and why. Later, you can flip back through those notes, inspect older versions, or create a separate path for an experiment.

## Why Git Matters

When you are learning to code, it is easy to treat files as fragile. You might avoid changing working code because you are afraid of breaking it. Git removes a lot of that fear.

With Git, you can:

- save working versions of your project
- see exactly what changed
- undo mistakes
- work on experiments without damaging your main code
- collaborate with other developers

Git is also the foundation for platforms like GitHub, GitLab, and Bitbucket. Those services host Git repositories online, but Git itself runs locally on your machine.

## Install Git

First, check whether Git is already installed:

```bash
git --version
```

On Linux, you can usually install it with your package manager:

```bash
sudo apt install git
```

On macOS, installing Xcode command line tools or using Homebrew works:

```bash
brew install git
```

On Windows, install Git for Windows from the official Git website. It includes Git Bash, which gives you a terminal that works well with Git commands.

## Configure Your Name and Email

Git records who made each commit. Set your name and email once:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

You can check your settings with:

```bash
git config --global --list
```

These values do not have to be secret. They are attached to your commits so people can see who made a change.

## Create Your First Repository

A Git repository is just a project folder where Git is tracking changes.

Create a small test project:

```bash
mkdir my-first-git-project
cd my-first-git-project
git init
```

The `git init` command creates a hidden `.git` directory. That directory stores Git's history and metadata. You usually do not edit it by hand.

Now create a file:

```bash
echo "Hello, Git!" > hello.txt
```

Ask Git what changed:

```bash
git status
```

Git should tell you that `hello.txt` is untracked. That means the file exists, but Git is not saving it in history yet.

## Stage and Commit Changes

Git has two important steps: staging and committing.

Staging means, "I want this change included in the next snapshot." Committing means, "Save this snapshot permanently in the project history."

Stage the file:

```bash
git add hello.txt
```

Now commit it:

```bash
git commit -m "Add hello text file"
```

The message should explain what changed. Good commit messages are short but specific. "Fix stuff" is not very helpful. "Add hello text file" is simple and clear.

## Make Another Change

Edit the file:

```bash
echo "Git helps track project history." >> hello.txt
```

Check the status:

```bash
git status
```

See the exact difference:

```bash
git diff
```

This shows what changed since the last commit. It is one of the most useful Git commands because it lets you review your work before saving it.

Stage and commit again:

```bash
git add hello.txt
git commit -m "Explain what Git does"
```

## View Your History

To see your commits:

```bash
git log --oneline
```

You will see a compact history, with each commit represented by a short ID and message.

This history is the main reason Git is so useful. Your project is no longer just a folder of files. It is a timeline of intentional changes.

## A Simple Mental Model

Here is a beginner-friendly way to think about Git:

- your working directory is your desk
- staging is choosing what papers to put in an envelope
- committing is sealing the envelope and labeling it
- history is the stack of labeled envelopes

You can keep working at your desk, but each commit gives you a stable checkpoint.

## What to Learn Next

Once you are comfortable with `status`, `add`, `commit`, `diff`, and `log`, learn these next:

- `git branch` for creating alternate lines of work
- `git switch` for moving between branches
- `git restore` for undoing local changes
- `git remote` for connecting to GitHub or GitLab
- `git push` and `git pull` for syncing with a remote repository

You do not need to learn all of Git at once. Start with small commits and clear messages. That habit alone will make your projects easier to understand and safer to change.

## Final Takeaway

Git is not just a tool for professional teams. It is useful from your very first project. It helps you experiment, recover, and understand how your code evolved. Learn the basic loop first: edit, check `git status`, review with `git diff`, stage with `git add`, and save with `git commit`.

That loop is the foundation of almost everything else in Git.
