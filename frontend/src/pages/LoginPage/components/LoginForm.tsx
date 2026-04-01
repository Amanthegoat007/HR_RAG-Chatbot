import {
  Button,
  Stack,
  Text,
  Box,
  TextInput,
  PasswordInput,
  Title,
  Container,
  Divider,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useNavigate } from "react-router-dom";
import { TbLock, TbMail } from "react-icons/tb";

import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { loginWithCredentials } from "@/store/slices/authSlice";

export default function LoginForm({
  setLoading,
}: {
  setLoading: (loading: boolean) => void;
}) {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { error } = useAppSelector((s) => s.auth);

  const form = useForm({
    initialValues: {
      username: "",
      password: "",
    },
    validate: {
      username: (value) =>
        value.length < 1 ? "Work username is required" : null,
      password: (value) => (value.length < 1 ? "Password is required" : null),
    },
  });

  const handleSubmit = (values: { username: string; password: string }) => {
    setLoading(true);
    dispatch(
      loginWithCredentials({
        username: values.username,
        password: values.password,
      }),
    )
      .unwrap()
      .then(() => {
        navigate("/copilot", { replace: true });
      })
      .catch((err) => {
        console.error("[LoginPage] Login failed:", err);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const inputStyles = {
    label: {
      color: "rgba(245, 248, 252, 0.92)",
      fontSize: "0.98rem",
      fontWeight: 600,
      marginBottom: 8,
    },
    input: {
      height: 54,
      backgroundColor: "rgba(40, 46, 56, 0.92)",
      border: "1px solid rgba(255, 255, 255, 0.12)",
      color: "#eef3ff",
      borderRadius: 12,
      boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)",
    },
    section: {
      color: "rgba(235, 240, 251, 0.65)",
    },
  } as const;

  return (
    <Box
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background:
          "radial-gradient(circle at 18% 18%, rgba(87, 116, 201, 0.08) 0%, rgba(87, 116, 201, 0) 26%), #171a1f",
      }}
    >
      <Container size={500} w="100%">
        <Stack gap="xl">
          <Stack gap={4}>
            <Title
              order={2}
              fw={700}
              size={40}
              style={{
                color: "#d7e3ff",
                letterSpacing: "-0.03em",
                lineHeight: 1.08,
              }}
            >
              Welcome to HR Copilot
            </Title>
            <Text
              size="sm"
              style={{
                color: "rgba(223, 230, 241, 0.82)",
                maxWidth: 460,
                lineHeight: 1.55,
                fontSize: "1.02rem",
              }}
            >
              Sign in with your work username.
            </Text>
          </Stack>

          <Divider color="rgba(255,255,255,0.12)" />

          <form onSubmit={form.onSubmit(handleSubmit)}>
            <Stack gap="md">
              {error && (
                <Text c="#ff8a8a" size="sm" fw={500}>
                  {error}
                </Text>
              )}

              <TextInput
                label="Work username"
                placeholder="Enter your work username"
                required
                leftSection={<TbMail size={18} />}
                radius="md"
                styles={inputStyles}
                {...form.getInputProps("username")}
              />

              <PasswordInput
                label="Password"
                placeholder="Enter your password"
                required
                leftSection={<TbLock size={18} />}
                radius="md"
                styles={inputStyles}
                {...form.getInputProps("password")}
              />

              <Button
                type="submit"
                mt="xl"
                radius="xl"
                styles={{
                  root: {
                    width: "fit-content",
                    height: 58,
                    paddingInline: 28,
                    background:
                      "linear-gradient(180deg, rgba(80, 92, 147, 0.95) 0%, rgba(56, 66, 109, 0.95) 100%)",
                    boxShadow: "0 14px 28px rgba(10, 12, 18, 0.28)",
                  },
                  label: {
                    fontSize: "1.02rem",
                    fontWeight: 700,
                    color: "#eef3ff",
                  },
                }}
              >
                Sign in
              </Button>
            </Stack>
          </form>
        </Stack>
      </Container>
    </Box>
  );
}
