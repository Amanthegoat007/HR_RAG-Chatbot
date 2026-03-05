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
      username: (value) => (value.length < 1 ? "Username is required" : null),
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

  return (
    <Box
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "var(--mantine-color-white)",
      }}
    >
      <Container size={420} w="100%">
        <Stack gap="xl">
          <Stack gap={4}>
            <Title order={2} fw={700} size={32} c="dark.7">
              Welcome Back
            </Title>
            <Text c="dimmed" size="sm">
              Sign in to access your utility analytics dashboard
            </Text>
          </Stack>

          <Divider />

          <form onSubmit={form.onSubmit(handleSubmit)}>
            <Stack gap="md">
              {error && (
                <Text c="red" size="sm" fw={500}>
                  {error}
                </Text>
              )}

              <TextInput
                label="Username"
                placeholder="Your email address"
                required
                leftSection={<TbMail size={18} />}
                {...form.getInputProps("username")}
              />

              <PasswordInput
                label="Password"
                placeholder="Your password"
                required
                leftSection={<TbLock size={18} />}
                {...form.getInputProps("password")}
              />

              <Button
                type="submit"
                mt="xl"
                color="dark.7"
                style={{ width: "fit-content", height: 48 }}
              >
                Sign In
              </Button>
            </Stack>
          </form>
        </Stack>
      </Container>
    </Box>
  );
}
