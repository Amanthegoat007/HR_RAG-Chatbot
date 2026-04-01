import {
  Stack,
  Button,
  Text,
  Group,
  ActionIcon,
  Collapse,
  Divider,
  ScrollArea,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  TbChevronRight,
  TbMenu2,
  TbSearch,
  TbTrash,
  TbEdit,
  TbChevronDown,
  TbFiles,
  TbActivityHeartbeat,
} from "react-icons/tb";
import { useState, useMemo } from "react";

import UserMenu from "@/layouts/components/UserMenu/UserMenu";
import { useLayout } from "@/layouts/LayoutContext";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  deleteConversation,
  startNewChat,
} from "@/store/slices/chatSlice";
import { useNavigate } from "react-router-dom";
import type { Conversation } from "@/types/chat.types";
import { ChatSearch } from "@/components/chat";

import type { SidebarProps } from "./Sidebar.types";
import classes from "./Sidebar.module.css";

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { conversations, activeConversationId } = useAppSelector((s) => s.chat);

  const [open, setOpen] = useState(true);
  const [isSearching, setIsSearching] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const { roles } = useAppSelector((s) => s.auth);
  const isAdmin =
    roles.includes("ROLE_ADMIN") || roles.includes("ROLE_ADMINISTRATOR");
  const isBenchmark = roles.includes("ROLE_BENCHMARK");

  const isMobile = useMediaQuery("(max-width: 768px)");
  const { toggleMobile } = useLayout();

  const filteredConversations = useMemo(() => {
    return conversations
      .filter((c: Conversation) => c.title && c.title.trim().length > 0)
      .filter((c: Conversation) =>
        c.title.toLowerCase().includes(searchQuery.toLowerCase()),
      );
  }, [conversations, searchQuery]);

  const handleStartNewChat = () => {
    setIsSearching(false);
    setSearchQuery("");
    dispatch(startNewChat());
    navigate("/copilot");
    if (isMobile) {
      toggleMobile();
    }
  };

  return (
    <Stack
      h="100%"
      p="sm"
      gap="xs"
      bg="body"
      className={classes.sidebarRoot}
      data-collapsed={collapsed}
    >
      <Group
        justify={collapsed ? "center" : "space-between"}
        px="xs"
        h={40}
        className={classes.header}
      >
        <ActionIcon
          variant="subtle"
          color="var(--mantine-color-text)"
          radius="md"
          size="lg"
          onClick={() => {
            if (isMobile) {
              toggleMobile();
            } else {
              onToggle(!collapsed);
            }
          }}
        >
          <TbMenu2 size={22} strokeWidth={1.5} />
        </ActionIcon>

        {!collapsed && (
          <ActionIcon
            variant="subtle"
            color={
              isSearching
                ? "var(--mantine-color-brand-filled)"
                : "var(--mantine-color-text)"
            }
            radius="md"
            size="lg"
            onClick={() => setIsSearching(!isSearching)}
          >
            <TbSearch size={22} strokeWidth={1.5} />
          </ActionIcon>
        )}
      </Group>

      <div
        className={`${classes.searchShell} ${isSearching && !collapsed ? classes.searchShellVisible : classes.searchShellHidden}`}
      >
        {isSearching && !collapsed && (
          <ChatSearch
            query={searchQuery}
            onQueryChange={setSearchQuery}
            onClear={() => {
              setIsSearching(false);
              setSearchQuery("");
            }}
          />
        )}
      </div>

      <Stack
        align={collapsed ? "center" : "stretch"}
        className={classes.contentArea}
        gap="sm"
      >
        {/* ... (rest of the component remains the same, but using filteredConversations) */}
        {collapsed && (
          <ActionIcon
            c="var(--mantine-color-text)"
            variant="transparent"
            className={classes.collapsedAction}
            type="button"
            onClick={handleStartNewChat}
          >
            <TbEdit size={18} />
          </ActionIcon>
        )}

        {!collapsed && (
          <>
            <Button
              type="button"
              leftSection={<TbEdit size={20} style={{ opacity: 0.8 }} />}
              variant="subtle"
              color="gray"
              fullWidth
              justify="flex-start"
              onClick={handleStartNewChat}
              className={classes.navButton}
            >
              New Chat
            </Button>

            {isAdmin && (
              <Button
                type="button"
                leftSection={<TbFiles size={20} style={{ opacity: 0.8 }} />}
                variant="subtle"
                color="gray"
                fullWidth
                justify="flex-start"
                onClick={() => {
                  navigate("/documents");
                  if (isMobile) toggleMobile();
                }}
                className={classes.navButton}
              >
                Documents
              </Button>
            )}

            {isBenchmark && (
              <Button
                type="button"
                leftSection={
                  <TbActivityHeartbeat size={20} style={{ opacity: 0.8 }} />
                }
                variant="subtle"
                color="gray"
                fullWidth
                justify="flex-start"
                onClick={() => {
                  navigate("/benchmark");
                  if (isMobile) toggleMobile();
                }}
                className={classes.navButton}
              >
                Monitoring / Benchmark
              </Button>
            )}

            <Divider />

            <Group
              justify="space-between"
              align="center"
              px="xs"
              mt="xs"
              mb={1}
              onClick={() => setOpen((o) => !o)}
              className={classes.sectionToggle}
            >
              <Text size="xs" fw={700} c="dimmed" className={classes.sectionLabel}>
                CHATS
              </Text>

              {open ? (
                <TbChevronDown size={14} />
              ) : (
                <TbChevronRight size={14} />
              )}
            </Group>
          </>
        )}

        {!collapsed && (
          <ScrollArea style={{ flex: 1 }} scrollbarSize={0}>
            <Collapse in={open}>
              <Stack gap={4}>
                {filteredConversations.length > 0
                  ? filteredConversations.map((c: Conversation) => {
                      const isActive = c.id === activeConversationId;

                      return (
                        <Group
                          key={c.id}
                          wrap="nowrap"
                          align="center"
                          px="xs"
                          py={6}
                          className={classes.conversationItem}
                          data-active={isActive}
                        >
                          <Button
                            type="button"
                            variant="subtle"
                            radius="md"
                            fullWidth
                            justify="flex-start"
                            className={`${classes.conversationButton} ${
                              isActive ? classes.conversationButtonActive : ""
                            }`}
                            onClick={() => {
                              navigate(`/copilot/c/${c.id}`);
                              if (isMobile) toggleMobile();
                            }}
                          >
                            {c.title}
                          </Button>

                          <ActionIcon
                            className={classes.deleteButton}
                            type="button"
                            variant="subtle"
                            color="var(--mantine-color-text)"
                            radius="xl"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (isActive) {
                                navigate("/copilot");
                              }
                              dispatch(deleteConversation(c.id));
                            }}
                          >
                            <TbTrash size={16} />
                          </ActionIcon>
                        </Group>
                      );
                    })
                  : searchQuery && (
                      <Text size="xs" c="dimmed" ta="center" py="md">
                        No chats found for "{searchQuery}"
                      </Text>
                    )}
              </Stack>
            </Collapse>
          </ScrollArea>
        )}
      </Stack>

      {!collapsed && <Divider />}
      <UserMenu collapsed={collapsed} />
    </Stack>
  );
}
